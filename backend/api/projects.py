"""Проекты, мастер, промпты, дорожная карта, память."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..core.audit import audit
from ..core.db import dumps, loads
from ..github.client import GitHubError
from ..memory import service as memory
from ..projects import wizard
from ..projects.analyzer import KIND_DEFAULT_TEMPLATE, KINDS, TEMPLATES, analyze
from ..prompts import generator
from ..roadmap import engine
from ..roadmap import service as roadmap
from .deps import client_ip, get_project, portal, require_owner

router = APIRouter(prefix="/api")

PUBLIC_FIELDS = ("id", "slug", "name", "kind", "template", "repo_full_name", "default_branch", "description",
                 "automation_enabled", "auto_merge_enabled", "auto_publish_releases", "prod_deploy_allowed",
                 "release_workflow", "release_artifact", "archived", "created_at")


def public(pr: dict) -> dict:
    out = {k: pr[k] for k in PUBLIC_FIELDS}
    for k in ("automation_enabled", "auto_merge_enabled", "auto_publish_releases", "prod_deploy_allowed", "archived"):
        out[k] = bool(out[k])
    out["required_checks"] = loads(pr["required_checks"], [])
    return out


def _gh_error(e: GitHubError):
    raise HTTPException(502 if e.status >= 500 or e.status == 401 else 400, str(e))


@router.get("/dashboard")
def dashboard(p=Depends(portal), _=Depends(require_owner)):
    db = p.db
    projects = db.all("SELECT * FROM projects WHERE archived=0 ORDER BY name")
    out = []
    for pr in projects:
        counts = {r["status"]: r["n"] for r in db.all(
            "SELECT status, count(*) AS n FROM tasks WHERE project_id=? GROUP BY status", (pr["id"],))}
        out.append({**public(pr), "tasks": counts,
                    "open_prs": db.one("SELECT count(*) AS n FROM pull_requests WHERE project_id=? AND state='open'", (pr["id"],))["n"],
                    "failing_prs": db.one("SELECT count(*) AS n FROM pull_requests WHERE project_id=? AND state='open' AND ci_state='failure'", (pr["id"],))["n"],
                    "last_release": db.one("SELECT version, published_at FROM releases WHERE project_id=? AND status='published' ORDER BY id DESC LIMIT 1", (pr["id"],))})
    actions = []
    for t in db.all("SELECT t.task_key, t.title, t.blocked_reason, p.name, p.id AS project_id FROM tasks t JOIN projects p ON p.id=t.project_id WHERE t.status='blocked' AND p.archived=0"):
        actions.append({"kind": "blocked", "project_id": t["project_id"], "text": f"{t['name']}: {t['task_key']} заблокирована — {t['blocked_reason']}"})
    for t in db.all("SELECT t.task_key, t.title, p.name, p.id AS project_id FROM tasks t JOIN projects p ON p.id=t.project_id WHERE t.status='ready' AND p.archived=0 LIMIT 20"):
        actions.append({"kind": "ready", "project_id": t["project_id"], "text": f"{t['name']}: выдать задачу {t['task_key']} «{t['title']}»"})
    from ..core import app_settings
    return {"projects": out, "actions": actions,
            "kill_switch": bool(app_settings.get(db, "global_kill_switch")),
            "unread": db.one("SELECT count(*) AS n FROM notifications WHERE is_read=0")["n"],
            "recent_merges": db.all("SELECT m.repo, m.number, m.ts FROM merge_attempts m WHERE m.decision='merge' ORDER BY id DESC LIMIT 5"),
            "servers": db.all("SELECT d.env, d.action, d.version, d.status, d.started_at, p.name FROM deploy_operations d JOIN projects p ON p.id=d.project_id ORDER BY d.id DESC LIMIT 5")}


@router.get("/projects")
def list_projects(p=Depends(portal), _=Depends(require_owner)):
    return [public(r) for r in p.db.all("SELECT * FROM projects ORDER BY archived, name")]


@router.get("/projects/{project_id}")
def project_detail(project=Depends(get_project)):
    return public(project)


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    repo_full_name: str | None = None
    default_branch: str | None = None
    automation_enabled: bool | None = None
    auto_merge_enabled: bool | None = None
    auto_publish_releases: bool | None = None
    prod_deploy_allowed: bool | None = None
    required_checks: list[str] | None = None
    release_workflow: str | None = None
    release_artifact: str | None = None
    archived: bool | None = None


@router.patch("/projects/{project_id}")
def patch_project(body: ProjectPatch, request: Request, project=Depends(get_project), p=Depends(portal)):
    data = body.model_dump(exclude_none=True)
    if "repo_full_name" in data and data["repo_full_name"]:
        import re
        if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", data["repo_full_name"]):
            raise HTTPException(400, "Репозиторий в формате владелец/имя")
    if "required_checks" in data:
        data["required_checks"] = dumps([c.strip() for c in data["required_checks"] if c.strip()][:30])
    for k in ("automation_enabled", "auto_merge_enabled", "auto_publish_releases", "prod_deploy_allowed", "archived"):
        if k in data:
            data[k] = 1 if data[k] else 0
    if data:
        sets = ", ".join(f"{k}=?" for k in data)
        p.db.execute(f"UPDATE projects SET {sets} WHERE id=?", list(data.values()) + [project["id"]])
        audit(p.db, "owner", "project_updated", project["id"], body.model_dump(exclude_none=True), client_ip(request))
    return public(p.project(project["id"]))


# --- мастер
@router.get("/wizard/options")
def wizard_options(_=Depends(require_owner)):
    return {"kinds": KINDS, "templates": TEMPLATES, "kind_default_template": KIND_DEFAULT_TEMPLATE}


class AnalyzeIn(BaseModel):
    repo_full_name: str


@router.post("/wizard/analyze")
def wizard_analyze(body: AnalyzeIn, p=Depends(portal), _=Depends(require_owner)):
    gh = p.github()
    try:
        info = gh.repo(body.repo_full_name)
        tree = gh.tree(body.repo_full_name, info["default_branch"])
    except GitHubError as e:
        _gh_error(e)
    return {"default_branch": info["default_branch"], "private": info.get("private"),
            "description": info.get("description") or "", "analysis": analyze(tree)}


class WizardIn(BaseModel):
    params: dict[str, Any]
    digest: str = ""
    create_repo: bool = False
    private: bool = True


@router.post("/wizard/preview")
def wizard_preview(body: WizardIn, p=Depends(portal), _=Depends(require_owner)):
    try:
        if not body.params.get("repo_full_name") or body.create_repo:
            params = wizard.validate_params(body.params)
            files = generator.project_files(params, {"stack": []})
            return {"params": params, "repo_exists": False, "analysis": None,
                    "changes": [{"path": k, "action": "create", "content": v, "diff": "", "note": "Будет создан"} for k, v in files.items()],
                    "digest": "", "bootstrap_prompt": generator.director_bootstrap_prompt(params)}
        return wizard.build_preview(p.github(), body.params)
    except wizard.WizardError as e:
        raise HTTPException(400, str(e))
    except GitHubError as e:
        _gh_error(e)


@router.post("/wizard/apply")
def wizard_apply(body: WizardIn, p=Depends(portal), _=Depends(require_owner)):
    try:
        if not body.params.get("repo_full_name"):
            res = wizard.register_local(p, body.params)
            return {"project": public(res["project"]), "written": [], "skipped": [], "pull_request": None,
                    "bootstrap_prompt": res["bootstrap_prompt"]}
        res = wizard.apply(p, body.params, body.digest, create_repo=body.create_repo, private=body.private)
        res["project"] = public(res["project"])
        return res
    except wizard.WizardError as e:
        raise HTTPException(400, str(e))
    except GitHubError as e:
        _gh_error(e)


# --- промпты и обучающие файлы
def _params(project: dict) -> dict:
    return {"name": project["name"], "slug": project["slug"], "kind": project["kind"], "template": project["template"],
            "description": project["description"], "repo_full_name": project["repo_full_name"] or "",
            "default_branch": project["default_branch"]}


@router.get("/projects/{project_id}/prompts")
def project_prompts(project=Depends(get_project), p=Depends(portal)):
    params = _params(project)
    return {"bootstrap": generator.director_bootstrap_prompt(params),
            "handover": memory.handover_prompt(p.db, project),
            "files": generator.project_files(params, {"stack": []})}


@router.get("/projects/{project_id}/context")
def ai_context(project=Depends(get_project), p=Depends(portal)):
    return {"prompt": memory.handover_prompt(p.db, project)}


# --- дорожная карта
@router.get("/projects/{project_id}/roadmap")
def get_roadmap(project=Depends(get_project), p=Depends(portal)):
    plan = roadmap.export_plan(p.db, project)
    rows = {r["task_key"]: r for r in p.db.all("SELECT task_key, pr_number, ci_state, blocked_reason FROM tasks WHERE project_id=?", (project["id"],))}
    for t in plan["tasks"]:
        t.update({k: rows[t["id"]][k] for k in ("pr_number", "ci_state", "blocked_reason")})
    return {"plan": plan, "ready": [t["id"] for t in engine.ready(plan)], "lanes": engine.lanes(plan),
            "markdown": engine.render(plan)}


class PlanIn(BaseModel):
    plan: dict[str, Any]


@router.put("/projects/{project_id}/roadmap")
def put_roadmap(body: PlanIn, request: Request, project=Depends(get_project), p=Depends(portal)):
    try:
        plan = roadmap.import_plan(p.db, project, body.plan)
    except (engine.PlanError, KeyError, TypeError) as e:
        raise HTTPException(400, f"План некорректен: {e}")
    audit(p.db, "owner", "roadmap_imported", project["id"], {"tasks": len(plan["tasks"])}, client_ip(request))
    return {"plan": plan}


@router.post("/projects/{project_id}/roadmap/pull")
def pull_roadmap(request: Request, project=Depends(get_project), p=Depends(portal)):
    if not project["repo_full_name"]:
        raise HTTPException(400, "Репозиторий не подключён")
    try:
        f = p.github().get_file(project["repo_full_name"], "docs/work_plan.json", project["default_branch"])
    except GitHubError as e:
        _gh_error(e)
    if not f:
        raise HTTPException(404, "docs/work_plan.json не найден в репозитории")
    try:
        plan = roadmap.import_plan(p.db, project, json.loads(f[0]))
    except (ValueError, engine.PlanError) as e:
        raise HTTPException(400, f"План некорректен: {e}")
    audit(p.db, "owner", "roadmap_pulled", project["id"], {"tasks": len(plan["tasks"])}, client_ip(request))
    try:
        mf = p.github().get_file(project["repo_full_name"], "docs/context/modules.json", project["default_branch"])
        if mf:
            _store_index(p, project, json.loads(mf[0]))
    except (GitHubError, ValueError, HTTPException):
        pass
    return {"plan": plan}


@router.get("/projects/{project_id}/tasks/{key}/prompt")
def task_prompt(key: str, project=Depends(get_project), p=Depends(portal)):
    from ..blueprint import service as bps
    from ..github.fresh_context import snapshot, appendix
    try:
        fresh = snapshot(p, project)
    except GitHubError as e:
        raise HTTPException(503, f"Не удалось проверить GitHub перед выдачей промпта: {e}")
    bp = bps.approved(p.db, project["id"])
    if bp and any(t["id"] == key for t in bp["content"]["tasks"]):
        return {"prompt": bps.assignment(p, project, key, "generic") + appendix(fresh), "github_context": fresh}
    try:
        return {"prompt": roadmap.task_prompt(p.db, project, key) + appendix(fresh), "github_context": fresh}
    except engine.PlanError as e:
        raise HTTPException(404, str(e))


class StatusIn(BaseModel):
    status: str
    reason: str = ""


@router.post("/projects/{project_id}/tasks/{key}/status")
def task_status(key: str, body: StatusIn, request: Request, project=Depends(get_project), p=Depends(portal)):
    try:
        roadmap.set_status(p.db, project, key, body.status, reason=body.reason)
    except engine.PlanError as e:
        raise HTTPException(400, str(e))
    roadmap.refresh(p.db, project)
    memory.add(p.db, project["id"], "task", f"{key}: статус {body.status}", body.reason)
    audit(p.db, "owner", "task_status", project["id"], {"task": key, "status": body.status}, client_ip(request))
    return roadmap.get_task(p.db, project["id"], key)


# --- память
class MemoryIn(BaseModel):
    kind: str
    title: str
    body: str = ""
    ref: str = ""


@router.get("/projects/{project_id}/memory")
def get_memory(kind: str | None = None, project=Depends(get_project), p=Depends(portal)):
    return memory.list_(p.db, project["id"], kind)


@router.post("/projects/{project_id}/memory")
def add_memory(body: MemoryIn, project=Depends(get_project), p=Depends(portal)):
    try:
        mid = memory.add(p.db, project["id"], body.kind, body.title, body.body, body.ref)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": mid}


@router.delete("/projects/{project_id}/memory/{entry_id}")
def del_memory(entry_id: int, project=Depends(get_project), p=Depends(portal)):
    if not memory.delete(p.db, project["id"], entry_id):
        raise HTTPException(404, "Запись не найдена")
    return {"ok": True}


# --- NEXUS Smart Context
from ..context import engine as ctx  # noqa: E402


def _index(p, project: dict) -> dict:
    row = p.db.one("SELECT context_index FROM projects WHERE id=?", (project["id"],))
    idx = loads(row["context_index"], {}) or {}
    idx.pop("task_modules", None)
    return idx


@router.get("/projects/{project_id}/context-index")
def get_context_index(project=Depends(get_project), p=Depends(portal)):
    idx = _index(p, project)
    plan = roadmap.export_plan(p.db, project)
    return {"index": idx, "check": ctx.check(idx, plan), "markdown": ctx.render_index(idx, plan) if idx else ""}


class IndexIn(BaseModel):
    index: dict[str, Any]


def _store_index(p, project: dict, idx: dict) -> dict:
    res = ctx.check(idx, roadmap.export_plan(p.db, project))
    if res["errors"]:
        raise HTTPException(400, "Индекс некорректен: " + "; ".join(res["errors"]))
    cur = loads(p.db.one("SELECT context_index FROM projects WHERE id=?", (project["id"],))["context_index"], {}) or {}
    idx = dict(idx, task_modules=cur.get("task_modules", {}))
    p.db.execute("UPDATE projects SET context_index=? WHERE id=?", (dumps(idx), project["id"]))
    return res


@router.put("/projects/{project_id}/context-index")
def put_context_index(body: IndexIn, request: Request, project=Depends(get_project), p=Depends(portal)):
    res = _store_index(p, project, body.index)
    audit(p.db, "owner", "context_index_updated", project["id"], {"modules": len(body.index.get("modules", []))}, client_ip(request))
    return {"check": res}


@router.post("/projects/{project_id}/context-index/pull")
def pull_context_index(project=Depends(get_project), p=Depends(portal)):
    """Обновить индекс из репозитория и выявить устаревшие ссылки по фактическому дереву файлов."""
    if not project["repo_full_name"]:
        raise HTTPException(400, "Репозиторий не подключён")
    gh = p.github()
    try:
        f = gh.get_file(project["repo_full_name"], ctx.INDEX_PATH, project["default_branch"])
        tree = {t["path"] for t in gh.tree(project["repo_full_name"], project["default_branch"])}
    except GitHubError as e:
        _gh_error(e)
    if not f:
        raise HTTPException(404, f"{ctx.INDEX_PATH} не найден в репозитории")
    try:
        idx = json.loads(f[0])
    except ValueError:
        raise HTTPException(400, "modules.json: некорректный JSON")
    res = _store_index(p, project, idx)
    res["warnings"] += stale_refs(idx, tree)
    return {"check": res}


def stale_refs(idx: dict, tree: set[str]) -> list[str]:
    out = []
    dirs = {"/".join(x.split("/")[:i]) for x in tree for i in range(1, x.count("/") + 1)}
    for k, d in idx.get("docs", {}).items():
        if d["path"] not in tree:
            out.append(f"Документ {k}: файл {d['path']} отсутствует в репозитории")
    for m in idx.get("modules", []):
        for kind in ("paths", "contracts", "tests"):
            for pat in m.get(kind, []):
                base = ctx._pattern_base(pat)
                if base and base not in tree and base not in dirs:
                    out.append(f"Модуль {m['id']}: {kind} {pat} отсутствует в репозитории")
    return out


@router.get("/projects/{project_id}/tasks/{key}/context")
def task_context(key: str, level: str = "standard", project=Depends(get_project), p=Depends(portal)):
    # Validate request arguments before contacting external GitHub.
    if level not in ("brief", "standard", "extended"):
        raise HTTPException(400, "Недопустимый уровень контекста")
    from ..github.fresh_context import snapshot, appendix
    try:
        fresh = snapshot(p, project)
    except GitHubError as e:
        raise HTTPException(503, f"Не удалось проверить GitHub перед выдачей контекста: {e}")
    idx = _index(p, project)
    plan = roadmap.export_plan(p.db, project)
    try:
        text = ctx.pack(idx, plan, key, level)
    except ctx.ContextError as e:
        raise HTTPException(404 if "не найдена" in str(e) else 400, str(e))
    text += appendix(fresh)
    return {"prompt": text, "level": level, "chars": len(text), "github_context": fresh}
