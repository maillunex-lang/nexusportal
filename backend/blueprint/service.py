"""Импорт, проверка, утверждение и версионирование Blueprint; «Что делать сейчас»."""
from __future__ import annotations

import hashlib
import json

from ..core.audit import audit
from ..core.db import dumps, loads
from ..memory import service as memory
from ..notifications.service import notify
from ..roadmap import service as roadmap
from . import core

TRACKED_FIELDS = ("title", "goal", "prompt", "acceptance_criteria", "depends_on", "priority", "phase",
                  "workstream", "resources", "conflicts_with", "verification")


class BlueprintServiceError(ValueError):
    pass


def _sha(doc: dict) -> str:
    return hashlib.sha256(json.dumps(doc, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def event(db, project_id: int, event_: str, task_id: str | None = None, detail: str = "", version: int | None = None):
    if version is None:
        row = db.one("SELECT version FROM blueprints WHERE project_id=? AND status='approved'", (project_id,))
        version = row["version"] if row else None
    db.insert("blueprint_events", {"project_id": project_id, "blueprint_version": version, "task_id": task_id,
                                   "event": event_, "detail": detail[:2000]})


def approved(db, project_id: int) -> dict | None:
    row = db.one("SELECT * FROM blueprints WHERE project_id=? AND status='approved'", (project_id,))
    return _row(row) if row else None


def _row(r: dict) -> dict:
    r = dict(r)
    r["content"] = loads(r["content"], {})
    r["validation"] = loads(r["validation"], {})
    r["changes"] = loads(r["changes"], {})
    return r


def diff(old: dict | None, new: dict) -> dict:
    old_t = {t["id"]: t for t in (old or {}).get("tasks", [])}
    new_t = {t["id"]: t for t in new["tasks"]}
    changed = []
    for k in new_t:
        if k in old_t:
            fields = [f for f in TRACKED_FIELDS if old_t[k].get(f) != new_t[k].get(f)]
            if fields:
                changed.append({"id": k, "fields": fields})
    return {"added": [k for k in new_t if k not in old_t], "removed": [k for k in old_t if k not in new_t],
            "changed": changed}


def submit(portal, project: dict, doc: dict, source: str = "upload", note: str = "", actor: str = "owner") -> dict:
    """Импорт: конвертация формата, проверка, сохранение черновика новой версии."""
    db = portal.db
    doc, fmt = core.detect_and_convert(doc)
    if fmt == "unknown":
        raise BlueprintServiceError(f"Неизвестный формат: ожидается «{core.FORMAT}» или план Adaptive Project Engine")
    res = core.validate(doc)
    if res["errors"]:
        raise core.BlueprintError(res["errors"])
    sha = _sha(doc)
    same = db.one("SELECT * FROM blueprints WHERE project_id=? AND sha256=? AND status IN ('draft','approved')",
                  (project["id"], sha))
    if same:
        return _row(same)
    cur = approved(db, project["id"])
    last = db.one("SELECT max(version) AS v FROM blueprints WHERE project_id=?", (project["id"],))
    version = (last["v"] or 0) + 1
    ch = diff(cur["content"] if cur else None, doc)
    bid = db.insert("blueprints", {"project_id": project["id"], "version": version, "doc_version": doc["blueprint_version"],
                                   "status": "draft", "content": dumps(doc), "sha256": sha, "source": source[:300],
                                   "source_format": fmt, "validation": dumps(res), "changes": dumps(ch), "note": note[:500]})
    event(db, project["id"], "blueprint_submitted", None, f"v{version} ({fmt}) из {source}", version)
    audit(db, actor, "blueprint_submitted", project["id"], {"version": version, "sha256": sha, "format": fmt})
    return _row(db.one("SELECT * FROM blueprints WHERE id=?", (bid,)))


def to_plan(project: dict, doc: dict) -> dict:
    return {
        "project": project["name"], "version": 2, "repo": project.get("repo_full_name") or "",
        "default_branch": project.get("default_branch") or "main", "gdd": (doc["sources"]["gdd"] or ["docs/GDD.md"])[0],
        "stages": [{"id": p["id"], "title": p["title"]} for p in doc["phases"]],
        "tasks": [{
            "id": t["id"], "title": t["title"], "stage": t["phase"], "lane": t.get("workstream") or "main",
            "goal": t["goal"], "context": t.get("context", ""), "gdd_refs": t.get("gdd_refs", []),
            "file_scope": t.get("scope_hints", []), "depends_on": t.get("depends_on", []),
            "done_when": t["acceptance_criteria"], "branch": core.branch_for(doc, t), "status": "planned",
        } for t in doc["tasks"]],
    }


def approve(portal, project: dict, blueprint_id: int, *, force: bool = False, actor: str = "owner") -> dict:
    db = portal.db
    row = db.one("SELECT * FROM blueprints WHERE id=? AND project_id=?", (blueprint_id, project["id"]))
    if not row:
        raise BlueprintServiceError("Версия не найдена")
    bp = _row(row)
    if bp["status"] != "draft":
        raise BlueprintServiceError("Утвердить можно только черновик")
    core.ensure_valid(bp["content"])
    cur = approved(db, project["id"])
    ch = diff(cur["content"] if cur else None, bp["content"])
    states = {r["task_key"]: r for r in db.all("SELECT task_key, status, pr_number FROM tasks WHERE project_id=?", (project["id"],))}
    busy = [k for k in ch["removed"] if states.get(k, {}).get("status") in ("in_progress", "blocked")]
    if busy and not force:
        raise BlueprintServiceError("Новая версия удаляет задачи в работе: " + ", ".join(busy)
                                    + ". Завершите их или подтвердите принудительное утверждение.")
    for k in ch["removed"]:
        event(db, project["id"], "task_removed", k, f"статус был {states.get(k, {}).get('status', '—')}", bp["version"])
        memory.add(db, project["id"], "task", f"{k} удалена из blueprint v{bp['version']}",
                   f"Статус на момент удаления: {states.get(k, {}).get('status', '—')}")
    for c in ch["changed"]:
        st = states.get(c["id"], {}).get("status")
        event(db, project["id"], "task_changed", c["id"], ", ".join(c["fields"]) + (f"; уже {st}" if st else ""), bp["version"])
    for k in ch["added"]:
        event(db, project["id"], "task_added", k, "", bp["version"])
    roadmap.import_plan(db, project, to_plan(project, bp["content"]))  # статусы и история задач сохраняются
    req = list(dict.fromkeys(loads(project["required_checks"], []) + bp["content"].get("conventions", {}).get("required_checks", [])))
    with db.transaction():
        db.execute("UPDATE blueprints SET status='superseded' WHERE project_id=? AND status='approved'", (project["id"],))
        db.execute("UPDATE blueprints SET status='approved', approved_at=datetime('now'), changes=? WHERE id=?",
                   (dumps(ch), blueprint_id))
        db.execute("UPDATE projects SET required_checks=? WHERE id=?", (dumps(req), project["id"]))
    event(db, project["id"], "blueprint_approved", None, f"v{bp['version']}: +{len(ch['added'])} −{len(ch['removed'])} ~{len(ch['changed'])}", bp["version"])
    audit(db, actor, "blueprint_approved", project["id"], {"version": bp["version"], "changes": ch, "force": force})
    memory.add(db, project["id"], "decision", f"Утверждён blueprint v{bp['version']} ({bp['doc_version']})",
               f"Добавлено {len(ch['added'])}, удалено {len(ch['removed'])}, изменено {len(ch['changed'])}")
    notify(portal, f"Утверждён blueprint v{bp['version']}", f"Задач: {len(bp['content']['tasks'])}", "success", project["id"])
    return _row(db.one("SELECT * FROM blueprints WHERE id=?", (blueprint_id,)))


def reject(portal, project: dict, blueprint_id: int, actor: str = "owner") -> None:
    cur = portal.db.execute("UPDATE blueprints SET status='rejected' WHERE id=? AND project_id=? AND status='draft'",
                            (blueprint_id, project["id"]))
    if cur.rowcount != 1:
        raise BlueprintServiceError("Отклонить можно только черновик")
    audit(portal.db, actor, "blueprint_rejected", project["id"], {"id": blueprint_id})


def task_states(db, project_id: int) -> dict[str, dict]:
    return {r["task_key"]: r for r in db.all(
        "SELECT task_key, status, pr_number, ci_state, blocked_reason, updated_at FROM tasks WHERE project_id=?", (project_id,))}


def now(portal, project: dict) -> dict:
    bp = approved(portal.db, project["id"])
    if not bp:
        return {"blueprint": None}
    doc = bp["content"]
    rows = task_states(portal.db, project["id"])
    sched = core.schedule(doc, {k: r["status"] for k, r in rows.items()})
    by = {t["id"]: t for t in doc["tasks"]}
    prs = {r["task_key"]: r for r in portal.db.all(
        "SELECT task_key, number, html_url, ci_state, head_sha FROM pull_requests WHERE project_id=? AND state='open'", (project["id"],))}

    def card(k: str, **extra) -> dict:
        t = by[k]
        r = rows.get(k, {})
        pr = prs.get(k)
        return {"id": k, "title": t["title"], "phase": t["phase"], "workstream": t.get("workstream", ""),
                "priority": t.get("priority", "P2"), "estimate": t.get("estimate", ""), "type": t.get("type", ""),
                "executor_hint": t.get("executor_hint", "any"), "goal": t["goal"], "status": r.get("status", "planned"),
                "blocked_reason": r.get("blocked_reason", ""), "pr": pr and {"number": pr["number"], "url": pr["html_url"], "ci": pr["ci_state"]},
                "branch": core.branch_for(doc, t), **extra}

    return {
        "blueprint": {"id": bp["id"], "version": bp["version"], "doc_version": bp["doc_version"], "approved_at": bp["approved_at"]},
        "now": [card(k) for k in sched["now"]],
        "attention": [card(a["id"]) for a in sched["active"] if a["status"] == "blocked"],
        "active": [card(a["id"]) for a in sched["active"] if a["status"] != "blocked"],
        "deferred": [card(d["id"], reason=d["reason"]) for d in sched["deferred"]],
        "waiting": [card(w["id"], waiting_for=w["waiting_for"]) for w in sched["waiting"]],
        "progress": sched["progress"], "phases": sched["phases"], "max_parallel": sched["max_parallel"],
        "order": sched["order"],
    }


def assignment(portal, project: dict, task_id: str, executor: str = "generic") -> str:
    bp = approved(portal.db, project["id"])
    if not bp:
        raise BlueprintServiceError("Нет утверждённого blueprint")
    rows = task_states(portal.db, project["id"])
    text = core.render_assignment(bp["content"], task_id, executor, project.get("repo_full_name") or "",
                                  project["default_branch"], {k: r["status"] for k, r in rows.items()})
    r = rows.get(task_id, {})
    if r.get("status") == "blocked" and r.get("pr_number"):
        from ..orchestration import automerge
        pr = portal.db.one("SELECT * FROM pull_requests WHERE project_id=? AND number=?", (project["id"], r["pr_number"]))
        if pr:
            text += "\n---\n" + automerge.repair_prompt(portal, project, pr)
    event(portal.db, project["id"], "assignment_copied", task_id, executor)
    return text


def history(portal, project: dict, task_id: str | None = None) -> list[dict]:
    if task_id:
        return portal.db.all("SELECT * FROM blueprint_events WHERE project_id=? AND task_id=? ORDER BY id DESC LIMIT 200",
                             (project["id"], task_id))
    return portal.db.all("SELECT * FROM blueprint_events WHERE project_id=? ORDER BY id DESC LIMIT 200", (project["id"],))
