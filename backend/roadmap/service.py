"""Синхронизация дорожной карты между work_plan.json и БД портала."""
from __future__ import annotations

from ..core.db import Database, dumps, loads
from . import engine

LIST_FIELDS = ("gdd_refs", "file_scope", "depends_on", "done_when")


def _task_row(r: dict) -> dict:
    t = {k: r[k] for k in ("title", "stage", "lane", "goal", "context", "branch", "status")}
    t["id"] = r["task_key"]
    for f in LIST_FIELDS:
        t[f] = loads(r[f], [])
    t["pr_number"] = r.get("pr_number")
    t["ci_state"] = r.get("ci_state", "")
    t["blocked_reason"] = r.get("blocked_reason", "")
    return t


def export_plan(db: Database, project: dict) -> dict:
    stages = db.all("SELECT stage_key, title FROM stages WHERE project_id=? ORDER BY position, id", (project["id"],))
    tasks = db.all("SELECT * FROM tasks WHERE project_id=? ORDER BY id", (project["id"],))
    return engine.normalize({
        "project": project["name"],
        "version": 2,
        "repo": project.get("repo_full_name") or "",
        "default_branch": project.get("default_branch") or "main",
        "gdd": "docs/GDD.md",
        "stages": [{"id": s["stage_key"], "title": s["title"]} for s in stages],
        "tasks": [_task_row(t) for t in tasks],
    })


def import_plan(db: Database, project: dict, plan: dict) -> dict:
    """Заменить этапы/задачи проекта планом. Статус done сохраняется только если он уже был в БД
    (done выставляет только подтверждённое слияние)."""
    plan = engine.normalize(plan)
    engine.check(plan)
    pid = project["id"]
    existing = {r["task_key"]: r for r in db.all("SELECT * FROM tasks WHERE project_id=?", (pid,))}
    with db.transaction():
        db.execute("DELETE FROM stages WHERE project_id=?", (pid,))
        for i, s in enumerate(plan["stages"]):
            db.execute("INSERT INTO stages(project_id, stage_key, title, position) VALUES (?,?,?,?)",
                       (pid, s["id"], s["title"], i))
        keep = set()
        for t in plan["tasks"]:
            keep.add(t["id"])
            old = existing.get(t["id"])
            status = t["status"]
            if status == "done" and not (old and old["status"] == "done"):
                status = "planned"
            if old and old["status"] in ("done", "in_progress", "blocked"):
                status = old["status"]
            vals = (t["title"], t["stage"], t["lane"], t["goal"], t["context"],
                    dumps(t["gdd_refs"]), dumps(t["file_scope"]), dumps(t["depends_on"]),
                    dumps(t["done_when"]), t["branch"], status)
            if old:
                db.execute("""UPDATE tasks SET title=?, stage=?, lane=?, goal=?, context=?, gdd_refs=?, file_scope=?,
                              depends_on=?, done_when=?, branch=?, status=?, updated_at=datetime('now')
                              WHERE project_id=? AND task_key=?""", vals + (pid, t["id"]))
            else:
                db.execute("""INSERT INTO tasks(title, stage, lane, goal, context, gdd_refs, file_scope, depends_on,
                              done_when, branch, status, project_id, task_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           vals + (pid, t["id"]))
        for k in existing:
            if k not in keep:
                db.execute("DELETE FROM tasks WHERE project_id=? AND task_key=?", (pid, k))
    refresh(db, project)
    return export_plan(db, project)


def refresh(db: Database, project: dict) -> list[str]:
    """Пересчитать готовые задачи. Вернуть ID задач, ставших ready."""
    plan = export_plan(db, project)
    before = {t["id"]: t["status"] for t in plan["tasks"]}
    engine.refresh_ready(plan)
    became = []
    for t in plan["tasks"]:
        if t["status"] != before[t["id"]]:
            db.execute("UPDATE tasks SET status=?, updated_at=datetime('now') WHERE project_id=? AND task_key=?",
                       (t["status"], project["id"], t["id"]))
            if t["status"] == "ready":
                became.append(t["id"])
    return became


def get_task(db: Database, project_id: int, key: str) -> dict | None:
    r = db.one("SELECT * FROM tasks WHERE project_id=? AND task_key=?", (project_id, key))
    return _task_row(r) if r else None


def set_status(db: Database, project: dict, key: str, status: str, *, reason: str = "",
               confirmed_merge: bool = False) -> None:
    if status not in engine.STATUSES:
        raise engine.PlanError("Некорректный статус")
    if status == "done" and not confirmed_merge:
        raise engine.PlanError("done выставляется только после подтверждённого слияния PR")
    cur = db.execute("UPDATE tasks SET status=?, blocked_reason=?, updated_at=datetime('now') WHERE project_id=? AND task_key=?",
                     (status, reason, project["id"], key))
    if cur.rowcount == 0:
        raise engine.PlanError(f"Задача {key} не найдена")


def task_prompt(db: Database, project: dict, key: str) -> str:
    return engine.prompt(export_plan(db, project), key)
