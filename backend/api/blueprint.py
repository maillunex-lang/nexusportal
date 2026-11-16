"""NEXUS Project Blueprint: импорт, проверка, утверждение, версии, «Что делать сейчас»."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..blueprint import core
from ..blueprint import service as bps
from ..core.audit import audit
from ..github.client import GitHubError
from .deps import client_ip, get_project, portal, require_owner

router = APIRouter(prefix="/api")
STANDARD_DIR = Path(__file__).resolve().parents[2] / "docs" / "blueprint"


def _err(e: Exception):
    if isinstance(e, core.BlueprintError):
        raise HTTPException(400, {"message": "Blueprint не прошёл проверку", "errors": e.errors})
    raise HTTPException(400, str(e))


@router.get("/blueprint/standard")
def standard(_=Depends(require_owner)):
    """Официальный стандарт: JSON Schema, шаблон, инструкция и промпт ИИ-архитектора."""
    def read(name):
        p = STANDARD_DIR / name
        return p.read_text(encoding="utf-8") if p.exists() else ""
    return {"format": core.FORMAT, "schema": read("blueprint.schema.json"), "template": read("template.json"),
            "guide": read("README.md"), "architect_prompt": read("ARCHITECT_PROMPT.md")}


@router.get("/blueprint/genre-knowledge/{genre_id}")
def genre_knowledge(genre_id: str, _=Depends(require_owner)):
    """Unapproved, source-linked research for the architect, never an executable Blueprint."""
    from tools.game_intelligence import blueprint_context
    try:
        result = blueprint_context(genre_id)
    except ValueError:
        raise HTTPException(404, "Неизвестный жанр")
    if result.get("status") != "unapproved_knowledge_context":
        raise HTTPException(503, "Контекст исследований не прошёл границу утверждения")
    return result


class ValidateIn(BaseModel):
    document: Any


@router.post("/blueprint/validate")
def validate(body: ValidateIn, _=Depends(require_owner)):
    doc, fmt = core.detect_and_convert(body.document)
    res = core.validate(doc)
    out = {"format": fmt, **res}
    if not res["errors"]:
        out["order"] = core.topo_order(doc)
        out["summary"] = {"phases": len(doc["phases"]), "tasks": len(doc["tasks"])}
    return out


@router.get("/projects/{project_id}/blueprints")
def versions(project=Depends(get_project), p=Depends(portal)):
    rows = p.db.all("""SELECT id, version, doc_version, status, sha256, source, source_format, validation, changes, note,
                       created_at, approved_at FROM blueprints WHERE project_id=? ORDER BY version DESC""", (project["id"],))
    for r in rows:
        r["validation"] = json.loads(r["validation"])
        r["changes"] = json.loads(r["changes"])
    return rows


@router.get("/projects/{project_id}/blueprints/{bid}")
def version(bid: int, project=Depends(get_project), p=Depends(portal)):
    row = p.db.one("SELECT * FROM blueprints WHERE id=? AND project_id=?", (bid, project["id"]))
    if not row:
        raise HTTPException(404, "Версия не найдена")
    return bps._row(row)


class SubmitIn(BaseModel):
    document: Any
    source: str = "вставка"
    note: str = ""


@router.post("/projects/{project_id}/blueprints")
def submit(body: SubmitIn, project=Depends(get_project), p=Depends(portal)):
    try:
        return bps.submit(p, project, body.document, body.source, body.note)
    except (core.BlueprintError, bps.BlueprintServiceError) as e:
        _err(e)


class PullIn(BaseModel):
    path: str = "docs/blueprint.json"


@router.post("/projects/{project_id}/blueprints/pull")
def pull(body: PullIn, project=Depends(get_project), p=Depends(portal)):
    if not project["repo_full_name"]:
        raise HTTPException(400, "Репозиторий не подключён")
    if body.path.startswith("/") or ".." in body.path.split("/"):
        raise HTTPException(400, "Некорректный путь")
    try:
        f = p.github().get_file(project["repo_full_name"], body.path, project["default_branch"])
    except GitHubError as e:
        raise HTTPException(502, str(e))
    if not f:
        raise HTTPException(404, f"{body.path} не найден в {project['default_branch']}")
    try:
        doc = json.loads(f[0])
    except ValueError:
        raise HTTPException(400, "Файл не является корректным JSON")
    try:
        return bps.submit(p, project, doc, f"GitHub {body.path}@{f[1][:10]}")
    except (core.BlueprintError, bps.BlueprintServiceError) as e:
        _err(e)


class ApproveIn(BaseModel):
    force: bool = False


@router.post("/projects/{project_id}/blueprints/{bid}/approve")
def approve(bid: int, body: ApproveIn, request: Request, project=Depends(get_project), p=Depends(portal)):
    try:
        return bps.approve(p, project, bid, force=body.force)
    except (core.BlueprintError, bps.BlueprintServiceError) as e:
        _err(e)


@router.post("/projects/{project_id}/blueprints/{bid}/reject")
def reject(bid: int, request: Request, project=Depends(get_project), p=Depends(portal)):
    try:
        bps.reject(p, project, bid)
    except bps.BlueprintServiceError as e:
        _err(e)
    audit(p.db, "owner", "blueprint_rejected", project["id"], {"id": bid}, client_ip(request))
    return {"ok": True}


@router.get("/projects/{project_id}/now")
def what_now(project=Depends(get_project), p=Depends(portal)):
    return bps.now(p, project)


@router.get("/now")
def what_now_all(p=Depends(portal), _=Depends(require_owner)):
    out = []
    for pr in p.db.all("SELECT * FROM projects WHERE archived=0 ORDER BY name"):
        n = bps.now(p, pr)
        if n["blueprint"]:
            out.append({"project": {"id": pr["id"], "name": pr["name"]}, "now": n["now"], "attention": n["attention"],
                        "progress": n["progress"]})
    return out


@router.get("/projects/{project_id}/tasks/{task_id}/assignment")
def assignment(task_id: str, executor: str = "generic", project=Depends(get_project), p=Depends(portal)):
    try:
        return {"prompt": bps.assignment(p, project, task_id, executor), "executor": executor}
    except (core.BlueprintError, bps.BlueprintServiceError) as e:
        _err(e)


@router.get("/projects/{project_id}/blueprint-history")
def history(task: str | None = None, project=Depends(get_project), p=Depends(portal)):
    return bps.history(p, project, task)
