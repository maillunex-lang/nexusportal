"""Изолированная память проекта и генерация «Контекста для ИИ»."""
from __future__ import annotations

from ..core.db import Database, loads
from ..core.redact import redact

KINDS = ("decision", "task", "error", "context", "doc")
KIND_TITLES = {"decision": "Решения", "task": "История задач", "error": "Ошибки",
               "context": "Контекст", "doc": "Документы"}


def add(db: Database, project_id: int, kind: str, title: str, body: str = "", ref: str = "") -> int:
    if kind not in KINDS:
        raise ValueError("Неизвестный тип записи памяти")
    return db.insert("memory_entries", {"project_id": project_id, "kind": kind,
                                        "title": redact(title)[:300], "body": redact(body)[:20000],
                                        "ref": ref[:500]})


def list_(db: Database, project_id: int, kind: str | None = None, limit: int = 200) -> list[dict]:
    if kind:
        return db.all("SELECT * FROM memory_entries WHERE project_id=? AND kind=? ORDER BY id DESC LIMIT ?",
                      (project_id, kind, limit))
    return db.all("SELECT * FROM memory_entries WHERE project_id=? ORDER BY id DESC LIMIT ?", (project_id, limit))


def delete(db: Database, project_id: int, entry_id: int) -> bool:
    return db.execute("DELETE FROM memory_entries WHERE project_id=? AND id=?", (project_id, entry_id)).rowcount == 1


def handover_prompt(db: Database, project: dict) -> str:
    """Актуальный промпт передачи дел ИИ-директору. Только данные этого проекта, без секретов."""
    pid = project["id"]
    tasks = db.all("SELECT * FROM tasks WHERE project_id=? ORDER BY id", (pid,))
    by_status: dict[str, list[dict]] = {}
    for t in tasks:
        by_status.setdefault(t["status"], []).append(t)
    prs = db.all("SELECT * FROM pull_requests WHERE project_id=? AND state='open' ORDER BY number", (pid,))
    rel = db.one("SELECT * FROM releases WHERE project_id=? AND status='published' ORDER BY id DESC LIMIT 1", (pid,))
    deploys = db.all("SELECT env, action, version, status, started_at FROM deploy_operations WHERE project_id=? ORDER BY id DESC LIMIT 5", (pid,))

    def section(kind: str, n: int) -> str:
        rows = list_(db, pid, kind, n)
        if not rows:
            return "- нет записей"
        return "\n".join(f"- [{r['created_at']}] {r['title']}" + (f": {r['body'][:400]}" if r["body"] else "")
                         + (f" ({r['ref']})" if r["ref"] else "") for r in rows)

    def tline(t: dict) -> str:
        extra = f" — PR #{t['pr_number']}" if t["pr_number"] else ""
        if t["blocked_reason"]:
            extra += f" — причина: {t['blocked_reason'][:200]}"
        return f"- {t['task_key']} {t['title']} [{t['lane']}]{extra}"

    def group(st: str) -> str:
        items = by_status.get(st, [])
        return "\n".join(tline(t) for t in items) if items else "- нет"

    total = len(tasks)
    done = len(by_status.get("done", []))
    text = f"""Ты — ИИ-директор проекта «{project['name']}» ({project['kind']}).
Репозиторий: {project.get('repo_full_name') or 'не подключён'}; базовая ветка: {project['default_branch']}.
Портал NEXUS PORTAL выполняет детерминированную автоматизацию: следит за PR и CI, сливает разрешённые PR после зелёного обязательного CI, публикует релизы. Сам портал не является ИИ.

Обязательно прочитай в репозитории: README.md, docs/GDD.md, docs/AI_RULES.md, docs/PORTAL_PROTOCOL.md, docs/DIRECTOR_HANDOVER.md, docs/work_plan.json.

## Прогресс
Выполнено {done} из {total} задач. Автослияние: {'включено' if project['auto_merge_enabled'] else 'выключено'}. Автоматизация: {'включена' if project['automation_enabled'] else 'выключена'}.

## В работе
{group('in_progress')}

## Готовы к выдаче (можно параллельно)
{group('ready')}

## Заблокированы
{group('blocked')}

## Ожидают зависимостей
{group('planned')}

## Открытые PR
{chr(10).join(f"- #{p['number']} {p['title']} — CI: {p['ci_state']}, SHA {p['head_sha'][:10]}" for p in prs) or '- нет'}

## Последний релиз
{f"- {rel['version']} ({rel['sha'][:10]}), {rel['download_url'] or 'ссылка не настроена'}" if rel else '- нет'}

## Последние операции развёртывания
{chr(10).join(f"- {d['started_at']} {d['env']} {d['action']} {d['version']}: {d['status']}" for d in deploys) or '- нет'}

## {KIND_TITLES['decision']}
{section('decision', 30)}

## {KIND_TITLES['error']} (последние)
{section('error', 10)}

## {KIND_TITLES['context']}
{section('context', 20)}

## {KIND_TITLES['doc']}
{section('doc', 20)}

## {KIND_TITLES['task']} (последние)
{section('task', 15)}

## Твои действия
1. Сверь состояние с docs/work_plan.json; общие файлы меняешь только ты.
2. Выдай исполнителям готовые задачи (кнопка «Промпт» в портале), не пересекая зоны файлов.
3. Для заблокированных задач используй промпт исправления из портала.
4. Ключевые решения согласуй с владельцем и зафиксируй в docs/gdd/DECISIONS_APPROVED.md.
5. Не запрашивай секреты в чате, не используй платные ИИ API.
"""
    return redact(text)
