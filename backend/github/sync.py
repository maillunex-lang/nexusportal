"""Отслеживание PR, коммитов и CI. Webhook-события + резервная сверка."""
from __future__ import annotations

import logging
import re

from ..core.db import dumps, loads

log = logging.getLogger("nexus.github")
PASS = {"success", "neutral", "skipped"}
FAIL = {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale", "error"}
TASK_IN_TITLE = re.compile(r"\[([A-Za-z][A-Za-z0-9_.-]{0,31})\]")


def detect_task(db, project: dict, branch: str, title: str) -> str | None:
    rows = db.all("SELECT task_key, branch FROM tasks WHERE project_id=?", (project["id"],))
    for r in rows:
        if r["branch"] and r["branch"] == branch:
            return r["task_key"]
    keys = {r["task_key"] for r in rows}
    for m in TASK_IN_TITLE.findall(title or ""):
        if m in keys:
            return m
    return None


def upsert_pr(portal, project: dict, pr: dict) -> dict:
    db = portal.db
    repo = project["repo_full_name"]
    head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name") or ""
    is_fork = bool(head_repo) and head_repo.lower() != repo.lower()
    branch = pr["head"]["ref"]
    task_key = detect_task(db, project, branch, pr.get("title", ""))
    state = "merged" if pr.get("merged") or pr.get("merged_at") else pr.get("state", "open")
    known = db.one("SELECT head_sha FROM pull_requests WHERE repo=? AND number=?", (repo, pr["number"]))
    if task_key and state == "open" and (known is None or known["head_sha"] != pr["head"]["sha"]):
        from ..blueprint import service as bps
        bps.event(db, project["id"], "pr_opened" if known is None else "pr_updated", task_key,
                  f"PR #{pr['number']} SHA {pr['head']['sha'][:10]}")
    db.execute("""INSERT INTO pull_requests(project_id, repo, number, title, branch, base, head_sha, state, merged,
                  merge_sha, is_fork, task_key, html_url, updated_at)
                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                  ON CONFLICT(repo, number) DO UPDATE SET title=excluded.title, branch=excluded.branch,
                  base=excluded.base, head_sha=excluded.head_sha, state=excluded.state, merged=excluded.merged,
                  merge_sha=COALESCE(excluded.merge_sha, pull_requests.merge_sha), is_fork=excluded.is_fork,
                  task_key=excluded.task_key, html_url=excluded.html_url, updated_at=datetime('now')""",
               (project["id"], repo, pr["number"], pr.get("title", ""), branch, pr["base"]["ref"],
                pr["head"]["sha"], state, 1 if state == "merged" else 0, pr.get("merge_commit_sha") if state == "merged" else None,
                1 if is_fork else 0, task_key, pr.get("html_url", "")))
    if task_key and state == "open":
        db.execute("""UPDATE tasks SET pr_number=?, status=CASE WHEN status IN ('planned','ready') THEN 'in_progress' ELSE status END,
                      updated_at=datetime('now') WHERE project_id=? AND task_key=? AND status!='done'""",
                   (pr["number"], project["id"], task_key))
    return db.one("SELECT * FROM pull_requests WHERE repo=? AND number=?", (repo, pr["number"]))


def collect_checks(gh, repo: str, sha: str) -> dict[str, dict]:
    """Состояние всех проверок для конкретного SHA: {имя: {state, url, summary}}."""
    out: dict[str, dict] = {}
    runs = sorted(gh.check_runs(repo, sha), key=lambda r: r.get("id", 0))
    for r in runs:
        if r.get("head_sha") and r["head_sha"] != sha:
            continue
        if r.get("status") != "completed":
            st = "pending"
        elif r.get("conclusion") in PASS:
            st = "success"
        else:
            st = "failure"
        out[r["name"]] = {"state": st, "url": r.get("html_url") or r.get("details_url") or "",
                          "summary": ((r.get("output") or {}).get("summary") or "")[:1500],
                          "run_id": _run_id(r.get("details_url") or "")}
    for s in gh.combined_status(repo, sha):
        if s["context"] in out:
            continue
        st = {"success": "success", "pending": "pending"}.get(s["state"], "failure")
        out[s["context"]] = {"state": st, "url": s.get("target_url") or "", "summary": s.get("description") or "",
                             "run_id": None}
    return out


def _run_id(url: str) -> int | None:
    m = re.search(r"/actions/runs/(\d+)", url)
    return int(m.group(1)) if m else None


def required_checks(gh, project: dict) -> list[str]:
    explicit = loads(project.get("required_checks"), []) or []
    try:
        protected = gh.required_checks(project["repo_full_name"], project["default_branch"])
    except Exception as e:
        log.warning("Не удалось прочитать защиту ветки: %s", e)
        protected = []
    names = list(dict.fromkeys(list(explicit) + list(protected)))
    return names


def ci_state(checks: dict[str, dict], required: list[str]) -> str:
    if not required:
        return "no_required_checks"
    states = [checks.get(n, {"state": "pending"})["state"] for n in required]
    if any(s == "failure" for s in states):
        return "failure"
    if all(s == "success" for s in states):
        return "success"
    return "pending"


def refresh_pr_checks(portal, project: dict, pr_row: dict, gh=None) -> dict:
    gh = gh or portal.github()
    checks = collect_checks(gh, pr_row["repo"], pr_row["head_sha"])
    req = required_checks(gh, project)
    state = ci_state(checks, req)
    portal.db.execute("UPDATE pull_requests SET checks=?, ci_state=?, updated_at=datetime('now') WHERE id=?",
                      (dumps({"required": req, "checks": checks}), state, pr_row["id"]))
    if pr_row.get("task_key"):
        portal.db.execute("UPDATE tasks SET ci_state=? WHERE project_id=? AND task_key=?",
                          (state, project["id"], pr_row["task_key"]))
    return portal.db.one("SELECT * FROM pull_requests WHERE id=?", (pr_row["id"],))


def record_commits(portal, repo: str, branch: str, commits: list[dict]) -> None:
    for c in commits[:50]:
        portal.db.execute("INSERT OR IGNORE INTO commits(repo, sha, branch, message, author) VALUES (?,?,?,?,?)",
                          (repo, c.get("id") or c.get("sha"), branch,
                           (c.get("message") or (c.get("commit") or {}).get("message") or "")[:500],
                           ((c.get("author") or {}).get("name") or ((c.get("commit") or {}).get("author") or {}).get("name") or "")))


def sync_project(portal, project: dict) -> dict:
    """Резервная сверка: открытые PR, CI, коммиты основной ветки, автослияние."""
    from ..orchestration import automerge
    gh = portal.github()
    repo = project["repo_full_name"]
    open_prs = gh.list_prs(repo, "open")
    seen = set()
    results = []
    for pr in open_prs:
        seen.add(pr["number"])
        row = upsert_pr(portal, project, pr)
        results.append(automerge.process_pr(portal, project, row["number"], gh=gh))
    # PR, которые закрылись/слились без доставленного webhook
    for row in portal.db.all("SELECT * FROM pull_requests WHERE project_id=? AND state='open'", (project["id"],)):
        if row["number"] not in seen:
            pr = gh.get_pr(repo, row["number"])
            upsert_pr(portal, project, pr)
            if pr.get("merged"):
                automerge.on_merged(portal, project, row["number"], pr.get("merge_commit_sha") or "")
    try:
        record_commits(portal, repo, project["default_branch"], gh.list_commits(repo, project["default_branch"], 10))
    except Exception as e:
        log.warning("commits: %s", e)
    return {"open_prs": len(open_prs), "decisions": results}


def handle_event(portal, event: str, payload: dict) -> str:
    """Обработать проверенное webhook-событие. Возвращает краткий итог."""
    from ..orchestration import automerge
    from ..releases import service as releases
    repo = (payload.get("repository") or {}).get("full_name") or ""
    project = portal.project_by_repo(repo)
    if not project:
        return "ignored: репозиторий не подключён"
    if event == "ping":
        return "pong"
    if event == "pull_request":
        pr = payload["pull_request"]
        upsert_pr(portal, project, pr)
        if payload.get("action") == "closed" and pr.get("merged"):
            automerge.on_merged(portal, project, pr["number"], pr.get("merge_commit_sha") or "")
            return "merged"
        if pr.get("state") == "open":
            return automerge.process_pr(portal, project, pr["number"])["decision"]
        return "updated"
    if event in ("check_suite", "check_run", "status"):
        sha = (payload.get("check_suite") or payload.get("check_run") or {}).get("head_sha") or payload.get("sha")
        rows = portal.db.all("SELECT number FROM pull_requests WHERE project_id=? AND state='open' AND head_sha=?",
                             (project["id"], sha))
        out = [automerge.process_pr(portal, project, r["number"])["decision"] for r in rows]
        return ",".join(out) or "no_pr"
    if event == "workflow_run":
        run = payload["workflow_run"]
        if payload.get("action") != "completed":
            return "ignored"
        res = []
        for n in [p["number"] for p in run.get("pull_requests") or []] or [
                r["number"] for r in portal.db.all(
                    "SELECT number FROM pull_requests WHERE project_id=? AND state='open' AND head_sha=?",
                    (project["id"], run.get("head_sha")))]:
            res.append(automerge.process_pr(portal, project, n)["decision"])
        rel = releases.handle_workflow_run(portal, project, run)
        return ",".join(res + [rel])
    if event == "push":
        branch = (payload.get("ref") or "").removeprefix("refs/heads/")
        record_commits(portal, repo, branch, payload.get("commits") or [])
        return "commits"
    return "ignored"
