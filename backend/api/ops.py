"""GitHub, CI, деплой, релизы, уведомления, настройки."""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ..core import app_settings
from ..core.audit import audit
from ..core.config import SECRET_NAMES, SecretError
from ..core.db import loads
from ..deploy import service as deploy
from ..github import sync, webhooks
from ..github.client import GitHubError
from ..notifications import service as notifications
from ..orchestration import automerge
from ..releases import service as releases
from ..releases.verify import ReleaseError
from .deps import client_ip, get_project, portal, require_owner

router = APIRouter(prefix="/api")
log = logging.getLogger("nexus.api")


# --- GitHub webhook (без cookie; подлинность — подпись HMAC SHA-256)
def _process_delivery(p, delivery: str, event: str, payload: dict) -> None:
    try:
        res = sync.handle_event(p, event, payload)
        webhooks.finish_delivery(p.db, delivery)
        log.info("webhook %s %s: %s", event, delivery, res)
    except Exception as e:  # ошибка не теряется: сохраняется и подхватится резервной сверкой
        webhooks.finish_delivery(p.db, delivery, str(e)[:500])
        log.exception("webhook %s failed", delivery)


@router.post("/github/webhook")
async def github_webhook(request: Request, background: BackgroundTasks, p=Depends(portal)):
    body = await request.body()
    if len(body) > 5_000_000:
        raise HTTPException(413, "Слишком большой запрос")
    try:
        secret = p.settings.secret("github_webhook_secret")
    except SecretError as e:
        raise HTTPException(500, str(e))
    if not webhooks.verify_signature(secret, body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "Неверная подпись")
    event = request.headers.get("x-github-event", "")
    delivery = request.headers.get("x-github-delivery", "")
    if not delivery or not event:
        raise HTTPException(400, "Нет заголовков доставки")
    payload = json.loads(body)
    repo = (payload.get("repository") or {}).get("full_name")
    if not webhooks.register_delivery(p.db, delivery, event, repo):
        return {"status": "duplicate"}
    background.add_task(_process_delivery, p, delivery, event, payload)
    return {"status": "accepted"}


@router.get("/github/status")
def github_status(p=Depends(portal), _=Depends(require_owner)):
    gh = p.github()
    out: dict[str, Any] = {"token_configured": gh.configured,
                           "webhook_secret_configured": p.settings.secret_status()["github_webhook_secret"],
                           "login": None, "error": None}
    if gh.configured:
        try:
            out["login"] = gh.me()["login"]
        except GitHubError as e:
            out["error"] = str(e)
    out["deliveries"] = p.db.all("SELECT delivery_id, event, repo, received_at, status, error FROM webhook_deliveries ORDER BY received_at DESC LIMIT 30")
    return out


@router.post("/projects/{project_id}/sync")
def project_sync(project=Depends(get_project), p=Depends(portal)):
    if not project["repo_full_name"]:
        raise HTTPException(400, "Репозиторий не подключён")
    try:
        return sync.sync_project(p, project)
    except GitHubError as e:
        raise HTTPException(502, str(e))


def _pr_out(r: dict) -> dict:
    r = dict(r)
    r["checks"] = loads(r["checks"], {})
    r["merged"] = bool(r["merged"])
    r["is_fork"] = bool(r["is_fork"])
    return r


@router.post("/projects/{project_id}/sync-and-state")
def sync_and_state(project=Depends(get_project), p=Depends(portal)):
    """Fresh GitHub reconciliation with explicit timestamp and branch SHA."""
    from datetime import datetime, timezone
    if not project["repo_full_name"]:
        raise HTTPException(400, "Репозиторий не подключён")
    try:
        result = sync.sync_project(p, project)
        sha = p.github().branch_sha(project["repo_full_name"], project["default_branch"] or "main")
    except GitHubError as e:
        raise HTTPException(502, f"GitHub недоступен, данные могут устареть: {e}")
    return {"synced_at": datetime.now(timezone.utc).isoformat(), "main_sha": sha,
            "branch": project["default_branch"] or "main", "sync": result}


@router.get("/projects/{project_id}/pulls")
def project_pulls(project=Depends(get_project), p=Depends(portal)):
    return [_pr_out(r) for r in p.db.all("SELECT * FROM pull_requests WHERE project_id=? ORDER BY state='open' DESC, number DESC LIMIT 100", (project["id"],))]


@router.get("/projects/{project_id}/commits")
def project_commits(project=Depends(get_project), p=Depends(portal)):
    return p.db.all("SELECT * FROM commits WHERE repo=? ORDER BY ts DESC LIMIT 50", (project["repo_full_name"] or "",))


@router.get("/projects/{project_id}/merge-log")
def merge_log(project=Depends(get_project), p=Depends(portal)):
    rows = p.db.all("SELECT * FROM merge_attempts WHERE project_id=? ORDER BY id DESC LIMIT 100", (project["id"],))
    for r in rows:
        r["reasons"] = loads(r["reasons"], [])
    return rows


@router.get("/projects/{project_id}/pulls/{number}/repair-prompt")
def repair(number: int, project=Depends(get_project), p=Depends(portal)):
    row = p.db.one("SELECT * FROM pull_requests WHERE project_id=? AND number=?", (project["id"], number))
    if not row:
        raise HTTPException(404, "PR не найден")
    return {"prompt": automerge.repair_prompt(p, project, row)}


@router.post("/projects/{project_id}/pulls/{number}/evaluate")
def evaluate_pr(number: int, project=Depends(get_project), p=Depends(portal)):
    try:
        return automerge.process_pr(p, project, number)
    except GitHubError as e:
        raise HTTPException(502, str(e))


@router.get("/ci")
def ci_overview(p=Depends(portal), _=Depends(require_owner)):
    rows = p.db.all("""SELECT pr.*, p.name AS project_name FROM pull_requests pr JOIN projects p ON p.id=pr.project_id
                       WHERE pr.state='open' ORDER BY pr.updated_at DESC LIMIT 100""")
    return [_pr_out(r) for r in rows]


# --- деплой
class RecipeIn(BaseModel):
    kind: str
    config: dict[str, Any] = {}
    script: str = ""


@router.get("/projects/{project_id}/deploy")
def deploy_overview(project=Depends(get_project), p=Depends(portal)):
    out = {"recipes": {}, "operations": p.db.all("SELECT * FROM deploy_operations WHERE project_id=? ORDER BY id DESC LIMIT 50", (project["id"],))}
    for env in ("dev", "prod"):
        r = deploy.active_recipe(p, project, env)
        if r:
            r["config"] = loads(r["config"], {})
        out["recipes"][env] = r
    out["base_dirs"] = {env: deploy.base_dir(p, project, env) for env in ("dev", "prod")}
    return out


@router.put("/projects/{project_id}/deploy/{env}/recipe")
def put_recipe(env: str, body: RecipeIn, project=Depends(get_project), p=Depends(portal)):
    try:
        r = deploy.save_recipe(p, project, env, body.kind, body.config, body.script)
    except deploy.DeployError as e:
        raise HTTPException(400, str(e))
    r["config"] = loads(r["config"], {})
    return r


@router.get("/projects/{project_id}/deploy/{env}/releases")
def remote_releases(env: str, project=Depends(get_project), p=Depends(portal)):
    try:
        return deploy.list_remote_releases(p, project, env)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/projects/{project_id}/deploy/{env}")
async def do_deploy(env: str, request: Request, version: str = Form(...), file: UploadFile = File(...),
                    project=Depends(get_project), p=Depends(portal)):
    with tempfile.TemporaryDirectory() as d:
        name = Path(file.filename or "artifact.bin").name
        path = Path(d) / "src"
        path.mkdir()
        (path / name).write_bytes(await file.read())
        if name.endswith((".tar.gz", ".tgz")):
            import tarfile
            with tarfile.open(path / name) as tar:
                tar.extractall(path / "x", filter="data")
            path = path / "x"
        try:
            op = deploy.deploy(p, project, env, version, path, actor="owner")
        except deploy.DeployError as e:
            raise HTTPException(400, str(e))
    return op


class RollbackIn(BaseModel):
    target: str | None = None


@router.post("/projects/{project_id}/deploy/{env}/rollback")
def do_rollback(env: str, body: RollbackIn, project=Depends(get_project), p=Depends(portal)):
    try:
        return deploy.rollback(p, project, env, body.target)
    except deploy.DeployError as e:
        raise HTTPException(400, str(e))


# --- релизы
@router.get("/projects/{project_id}/releases")
def list_releases(project=Depends(get_project), p=Depends(portal)):
    return p.db.all("SELECT * FROM releases WHERE project_id=? ORDER BY id DESC", (project["id"],))


@router.get("/releases")
def all_releases(p=Depends(portal), _=Depends(require_owner)):
    return p.db.all("SELECT r.*, p.name AS project_name, p.kind FROM releases r JOIN projects p ON p.id=r.project_id ORDER BY r.id DESC LIMIT 100")


class RunIn(BaseModel):
    run_id: int


@router.post("/projects/{project_id}/releases/process")
def process_release(body: RunIn, project=Depends(get_project), p=Depends(portal)):
    gh = p.github()
    try:
        run = gh.run(project["repo_full_name"], body.run_id)
        return releases.process_run(p, project, run, gh, actor="owner")
    except (ReleaseError, deploy.DeployError) as e:
        raise HTTPException(400, str(e))
    except GitHubError as e:
        raise HTTPException(502, str(e))


@router.post("/projects/{project_id}/releases/{version}/rollback")
def release_rollback(version: str, project=Depends(get_project), p=Depends(portal)):
    try:
        return releases.rollback(p, project, version)
    except (ReleaseError, deploy.DeployError) as e:
        raise HTTPException(400, str(e))


# --- уведомления
@router.get("/notifications")
def list_notifications(unread: bool = False, p=Depends(portal), _=Depends(require_owner)):
    return notifications.list_(p.db, unread)


@router.post("/notifications/read-all")
def read_all(p=Depends(portal), _=Depends(require_owner)):
    p.db.execute("UPDATE notifications SET is_read=1 WHERE is_read=0")
    return {"ok": True}


@router.post("/notifications/test")
def test_notification(p=Depends(portal), _=Depends(require_owner)):
    nid = notifications.notify(p, "Проверка уведомлений", "Если вы видите это сообщение, канал настроен.")
    return p.db.one("SELECT * FROM notifications WHERE id=?", (nid,))


# --- настройки
@router.get("/settings")
def get_settings(p=Depends(portal), _=Depends(require_owner)):
    s = p.settings
    return {"settings": app_settings.all_(p.db), "secrets": s.secret_status(),
            "server": {"deploy_root": s.deploy_root, "public_download_base": s.public_download_base,
                       "ssh_key_configured": bool(s.ssh_key_path and s.ssh_key_path.exists()),
                       "known_hosts_configured": bool(s.ssh_known_hosts and s.ssh_known_hosts.exists()),
                       "sync_interval_minutes": s.sync_interval_minutes}}


class SettingsIn(BaseModel):
    values: dict[str, Any]


VALIDATORS = {
    "global_kill_switch": lambda v: isinstance(v, bool),
    "notify_channels": lambda v: isinstance(v, list) and set(v) <= {"portal", "telegram", "max"},
    "deploy_executor": lambda v: v in ("ssh", "local"),
    "ssh_port": lambda v: isinstance(v, int) and 0 < v < 65536,
    "allowed_repos": lambda v: isinstance(v, list) and all(isinstance(x, str) and x.count("/") == 1 for x in v),
}


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, p=Depends(portal), _=Depends(require_owner)):
    for k, v in body.values.items():
        if k not in app_settings.DEFAULTS:
            raise HTTPException(400, f"Неизвестная настройка {k}")
        check = VALIDATORS.get(k, lambda v: isinstance(v, str) and len(v) < 300)
        if not check(v):
            raise HTTPException(400, f"Некорректное значение {k}")
    for k, v in body.values.items():
        app_settings.set_(p.db, k, v)
    audit(p.db, "owner", "settings_updated", None, body.values, client_ip(request))
    return app_settings.all_(p.db)


class SecretIn(BaseModel):
    value: str


@router.put("/settings/secrets/{name}")
def put_secret(name: str, body: SecretIn, request: Request, p=Depends(portal), _=Depends(require_owner)):
    """Секрет записывается в файл 0600 на сервере и никогда не возвращается обратно."""
    if name not in SECRET_NAMES:
        raise HTTPException(404, "Неизвестный секрет")
    if not body.value.strip() or len(body.value) > 500:
        raise HTTPException(400, "Пустое или слишком длинное значение")
    p.settings.write_secret(name, body.value)
    audit(p.db, "owner", "secret_updated", None, {"name": name}, client_ip(request))
    return {"ok": True, "configured": True}


@router.get("/audit")
def audit_log(project_id: int | None = None, p=Depends(portal), _=Depends(require_owner)):
    if project_id:
        return p.db.all("SELECT * FROM audit_log WHERE project_id=? ORDER BY id DESC LIMIT 200", (project_id,))
    return p.db.all("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200")
