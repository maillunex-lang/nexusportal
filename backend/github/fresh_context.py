"""Fresh GitHub reconciliation for director prompts; fail closed on errors."""
from __future__ import annotations
from datetime import datetime, timezone
from .client import GitHubError
from .sync import sync_project

def snapshot(portal, project: dict) -> dict:
    repo = project.get("repo_full_name")
    if not repo:
        raise GitHubError(400, "У проекта нет подключённого репозитория")
    branch = project.get("default_branch") or "main"
    gh = portal.github()
    before = gh.branch_sha(repo, branch)
    result = sync_project(portal, project)
    after = gh.branch_sha(repo, branch)
    if before != after:
        raise GitHubError(409, "Ветка изменилась во время синхронизации; повторите запрос")
    tasks = portal.db.all("SELECT task_key,title,status,pr_number FROM tasks WHERE project_id=? ORDER BY task_key", (project["id"],))
    prs = portal.db.all("SELECT number,title,head_sha,ci_state,state,merged,task_key FROM pull_requests WHERE project_id=? AND state=? ORDER BY number", (project["id"], "open"))
    return {"repo": repo, "branch": branch, "main_sha": after, "synced_at": datetime.now(timezone.utc).isoformat(), "tasks": tasks, "open_prs": prs, "sync": result}

def appendix(data: dict) -> str:
    lines = ["", "## Подтверждённое состояние GitHub перед ответом", "Репозиторий: {}".format(data["repo"]), "Ветка: {}; SHA: {}".format(data["branch"], data["main_sha"]), "Проверено UTC: {}".format(data["synced_at"]), "Задачи (ready = можно начинать, done = завершена):"]
    lines.extend("- {}: {}; PR #{}".format(t["task_key"], t["status"], t["pr_number"] or "-") for t in data["tasks"])
    lines.append("Открытые PR и CI:")
    lines.extend("- #{} {}; CI={}; SHA={}".format(pr["number"], pr["title"], pr["ci_state"], pr["head_sha"]) for pr in data["open_prs"])
    lines.append("SHA и PR не подтверждают содержимое конкретного файла. Для утверждений о коде отдельно читай GitHub.")
    return "\n".join(lines)
