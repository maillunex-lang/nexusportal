"""Автоматическое слияние разрешённых PR после зелёного обязательного CI.

Правила (docs/GDD.md, «GitHub и CI»):
- проверяется актуальный head SHA, полученный из API в момент решения;
- обязательные проверки явно заданы (проект или защита ветки) и все успешны на этом SHA;
- PR принадлежит задаче проекта, направлен в основную ветку, не из форка;
- нет глобального/проектного аварийного выключателя, автослияние разрешено для проекта;
- слияние выполняется с параметром sha (идемпотентно), done ставится только после подтверждённого слияния;
- при ошибке CI задача блокируется и формируется готовый промпт исправления.
"""
from __future__ import annotations

import logging

from ..core import app_settings
from ..core.audit import audit
from ..core.db import dumps, loads
from ..github import sync
from ..github.client import GitHubError
from ..memory import service as memory
from ..notifications.service import notify
from ..roadmap import service as roadmap

log = logging.getLogger("nexus.automerge")


def evaluate(portal, project: dict, pr_api: dict, pr_row: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    blocked = app_settings.automation_blocked(portal.db, project)
    if blocked:
        reasons.append(blocked)
    if not project["auto_merge_enabled"]:
        reasons.append("Автослияние для проекта не разрешено владельцем")
    if pr_api["base"]["ref"] != project["default_branch"]:
        reasons.append(f"PR направлен не в {project['default_branch']}")
    if pr_row["is_fork"]:
        reasons.append("PR из форка — автоматические действия запрещены")
    if not pr_row["task_key"]:
        reasons.append("PR не привязан к задаче дорожной карты")
    else:
        t = roadmap.get_task(portal.db, project["id"], pr_row["task_key"])
        if t and t["status"] == "done":
            reasons.append("Задача уже выполнена")
    if pr_api.get("draft"):
        reasons.append("PR в статусе черновика")
    if pr_api["head"]["sha"] != pr_row["head_sha"]:
        reasons.append("SHA PR изменился во время проверки")
    checks = loads(pr_row["checks"], {})
    if not checks.get("required"):
        reasons.append("Не заданы обязательные проверки CI")
    ci = pr_row["ci_state"]
    if ci == "failure":
        return "ci_failed", reasons + ["Обязательный CI завершился с ошибкой"]
    if ci != "success":
        reasons.append("Обязательный CI ещё не завершён")
    mergeable = pr_api.get("mergeable")
    if mergeable is False:
        reasons.append("PR имеет конфликты слияния")
    elif mergeable is None:
        reasons.append("GitHub ещё вычисляет возможность слияния")
    return ("merge" if not reasons else "wait"), reasons


def _record(portal, project, pr_row, decision, reasons) -> bool:
    """Записать решение; True если это новое решение для данного SHA."""
    last = portal.db.one("SELECT decision, reasons FROM merge_attempts WHERE repo=? AND number=? AND head_sha=? ORDER BY id DESC LIMIT 1",
                         (pr_row["repo"], pr_row["number"], pr_row["head_sha"]))
    if last and last["decision"] == decision and last["reasons"] == dumps(reasons):
        return False
    portal.db.insert("merge_attempts", {"project_id": project["id"], "repo": pr_row["repo"], "number": pr_row["number"],
                                        "head_sha": pr_row["head_sha"], "decision": decision, "reasons": dumps(reasons)})
    return True


def repair_prompt(portal, project: dict, pr_row: dict, gh=None) -> str:
    checks = loads(pr_row["checks"], {})
    failing = {n: c for n, c in checks.get("checks", {}).items()
               if n in checks.get("required", []) and c["state"] == "failure"}
    details = []
    for name, c in failing.items():
        line = f"- **{name}**: {c.get('url') or ''}"
        if c.get("summary"):
            line += f"\n  Итог: {c['summary'][:800]}"
        if gh and c.get("run_id"):
            try:
                for j in gh.failed_jobs(pr_row["repo"], c["run_id"]):
                    steps = [s["name"] for s in j.get("steps") or [] if s.get("conclusion") == "failure"]
                    line += f"\n  Задание «{j['name']}» упало на шагах: {', '.join(steps) or 'не указано'}"
            except Exception:
                pass
        details.append(line)
    task_part = ""
    if pr_row["task_key"]:
        try:
            task_part = "\n\n## Исходная задача\n" + roadmap.task_prompt(portal.db, project, pr_row["task_key"])
        except Exception:
            pass
    return f"""Исправь ошибку CI в PR #{pr_row['number']} проекта «{project['name']}».
Репозиторий: {pr_row['repo']}; ветка: {pr_row['branch']}; SHA: {pr_row['head_sha']}.
Ссылка: {pr_row['html_url']}

## Упавшие обязательные проверки
{chr(10).join(details) or '- нет данных (см. вкладку Checks в PR)'}

## Что сделать
1. Получи актуальную ветку `{pr_row['branch']}` и воспроизведи ошибку локально.
2. Исправь причину, не отключая и не ослабляя тесты и проверки.
3. Запушь исправление в ту же ветку — портал заново проверит CI и сольёт PR автоматически.
4. Не меняй файлы вне зоны задачи и не добавляй секреты.{task_part}
"""


def process_pr(portal, project: dict, number: int, gh=None) -> dict:
    gh = gh or portal.github()
    repo = project["repo_full_name"]
    pr_api = gh.get_pr(repo, number)
    pr_row = sync.upsert_pr(portal, project, pr_api)
    if pr_api.get("merged"):
        on_merged(portal, project, number, pr_api.get("merge_commit_sha") or "")
        return {"number": number, "decision": "merged", "reasons": []}
    if pr_api.get("state") != "open":
        return {"number": number, "decision": "closed", "reasons": []}
    pr_row = sync.refresh_pr_checks(portal, project, pr_row, gh)
    decision, reasons = evaluate(portal, project, pr_api, pr_row)
    is_new = _record(portal, project, pr_row, decision, reasons)
    result = {"number": number, "decision": decision, "reasons": reasons, "sha": pr_row["head_sha"]}

    if decision == "ci_failed":
        prompt = repair_prompt(portal, project, pr_row, gh)
        result["repair_prompt"] = prompt
        if is_new:
            if pr_row["task_key"]:
                roadmap.set_status(portal.db, project, pr_row["task_key"], "blocked",
                                   reason=f"CI упал на {pr_row['head_sha'][:10]} (PR #{number})")
            memory.add(portal.db, project["id"], "error", f"CI упал: PR #{number} {pr_row['title']}",
                       prompt[:3000], pr_row["html_url"])
            notify(portal, f"CI упал: PR #{number}", f"{pr_row['title']}\nПромпт исправления готов в портале.",
                   "error", project["id"])
        return result

    if pr_row["task_key"] and pr_row["ci_state"] in ("pending", "success"):
        t = roadmap.get_task(portal.db, project["id"], pr_row["task_key"])
        if t and t["status"] == "blocked" and t["blocked_reason"].startswith("CI упал"):
            roadmap.set_status(portal.db, project, pr_row["task_key"], "in_progress")

    if decision != "merge":
        return result

    title = f"{pr_api['title']} (#{number})"
    try:
        resp = gh.merge_pr(repo, number, sha=pr_row["head_sha"], title=title)
    except GitHubError as e:
        _record(portal, project, pr_row, "merge_rejected", [str(e)])
        audit(portal.db, "automation", "merge_rejected", project["id"], {"pr": number, "error": str(e)})
        result.update(decision="merge_rejected", reasons=[str(e)])
        return result
    audit(portal.db, "automation", "merge", project["id"],
          {"pr": number, "sha": pr_row["head_sha"], "merged": bool(resp and resp.get("merged"))})
    if resp and resp.get("merged"):
        on_merged(portal, project, number, resp.get("sha") or "")
        result["decision"] = "merged"
    return result


def on_merged(portal, project: dict, number: int, merge_sha: str) -> list[str]:
    """Подтверждённое слияние: задача -> done, открыть следующие. Идемпотентно."""
    db = portal.db
    row = db.one("SELECT * FROM pull_requests WHERE repo=? AND number=?", (project["repo_full_name"], number))
    if not row:
        return []
    db.execute("UPDATE pull_requests SET state='merged', merged=1, merge_sha=COALESCE(NULLIF(?, ''), merge_sha) WHERE id=?",
               (merge_sha, row["id"]))
    if not row["task_key"]:
        return []
    task = roadmap.get_task(db, project["id"], row["task_key"])
    if not task or task["status"] == "done":
        return []
    roadmap.set_status(db, project, row["task_key"], "done", confirmed_merge=True)
    became = roadmap.refresh(db, project)
    memory.add(db, project["id"], "task", f"{row['task_key']} выполнена: PR #{number} слит",
               f"SHA слияния {merge_sha[:12]}", row["html_url"])
    notify(portal, f"Задача {row['task_key']} выполнена",
           f"PR #{number} слит.\nГотовы к выдаче: {', '.join(became) or 'нет новых'}", "success", project["id"])
    return became
