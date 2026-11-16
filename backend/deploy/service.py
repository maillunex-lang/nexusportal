"""Развёртывание проектов: dev/prod, версионированные сценарии, резервные копии, атомарная замена, откат.

Структура на VPS (только внутри собственного каталога проекта):
  {deploy_root}/{slug}/{env}/releases/<version>/   — неизменяемые релизы
  {deploy_root}/{slug}/{env}/current -> releases/<version>  — атомарная символическая ссылка
  {deploy_root}/{slug}/{env}/shared/                — данные, переживающие релизы
  {deploy_root}/{slug}/{env}/backups/               — архивы перед каждой операцией
Команды из PR никогда не выполняются: сценарий хранится в портале и задаётся владельцем.
"""
from __future__ import annotations

import hashlib
import re
import shlex
import tempfile
from pathlib import Path

from ..core import app_settings
from ..core.audit import audit
from ..core.db import dumps, loads
from ..memory import service as memory
from ..notifications.service import notify

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
UNIT_RE = re.compile(r"^[a-z0-9@._-]+\.service$")
KINDS = ("static", "script")
KEEP_RELEASES = 3  # текущий + 2 для отката


class DeployError(RuntimeError):
    pass


def base_dir(portal, project: dict, env: str) -> str:
    if env not in ("dev", "prod"):
        raise DeployError("Окружение должно быть dev или prod")
    if not SLUG_RE.match(project["slug"]):
        raise DeployError("Некорректный slug проекта")
    root = portal.settings.deploy_root.rstrip("/")
    if not root.startswith("/") or ".." in root:
        raise DeployError("Некорректный корень развёртывания")
    return f"{root}/{project['slug']}/{env}"


def validate_recipe(project: dict, env: str, kind: str, config: dict, script: str) -> None:
    if kind not in KINDS:
        raise DeployError("Тип сценария: static или script")
    unit = config.get("systemd_unit") or ""
    if unit:
        prefix = f"nexus-{project['slug']}-"
        if not UNIT_RE.match(unit) or not unit.startswith(prefix):
            raise DeployError(f"Служба должна называться {prefix}<имя>.service — чужие службы трогать нельзя")
    hc = config.get("healthcheck_url") or ""
    if hc and not re.match(r"^https?://[A-Za-z0-9.:/_?=&%-]+$", hc):
        raise DeployError("Некорректный адрес проверки работоспособности")
    if kind == "script" and not script.strip():
        raise DeployError("Сценарий не может быть пустым")
    if len(script) > 20000:
        raise DeployError("Сценарий слишком длинный")


def save_recipe(portal, project: dict, env: str, kind: str, config: dict, script: str, actor: str = "owner") -> dict:
    validate_recipe(project, env, kind, config, script)
    db = portal.db
    prev = db.one("SELECT max(version) AS v FROM deploy_recipes WHERE project_id=? AND env=?", (project["id"], env))
    version = (prev["v"] or 0) + 1
    digest = hashlib.sha256((kind + dumps(config) + script).encode()).hexdigest()
    with db.transaction():
        db.execute("UPDATE deploy_recipes SET active=0 WHERE project_id=? AND env=?", (project["id"], env))
        rid = db.insert("deploy_recipes", {"project_id": project["id"], "env": env, "kind": kind,
                                           "config": dumps(config), "script": script, "version": version,
                                           "sha256": digest, "active": 1})
    audit(db, actor, "deploy_recipe_saved", project["id"], {"env": env, "version": version, "sha256": digest})
    return db.one("SELECT * FROM deploy_recipes WHERE id=?", (rid,))


def active_recipe(portal, project: dict, env: str) -> dict | None:
    return portal.db.one("SELECT * FROM deploy_recipes WHERE project_id=? AND env=? AND active=1", (project["id"], env))


def _check_allowed(portal, project: dict, env: str, automated: bool) -> None:
    if automated:
        blocked = app_settings.automation_blocked(portal.db, project)
        if blocked:
            raise DeployError(blocked)
    if env == "prod" and not project["prod_deploy_allowed"]:
        raise DeployError("Продакшен-деплой для проекта не разрешён владельцем")


def _op_start(portal, project, env, action, version, recipe_id=None) -> int:
    return portal.db.insert("deploy_operations", {"project_id": project["id"], "env": env, "action": action,
                                                  "version": version, "recipe_id": recipe_id})


def _op_finish(portal, op_id, status, log, prev="", backup=""):
    portal.db.execute("UPDATE deploy_operations SET status=?, log=?, previous_version=?, backup_path=?, finished_at=datetime('now') WHERE id=?",
                      (status, log[-20000:], prev, backup, op_id))


def _q(s: str) -> str:
    return shlex.quote(s)


def remote_deploy_script(base: str, version: str, archive: str, recipe: dict) -> str:
    cfg = loads(recipe["config"], {})
    unit = cfg.get("systemd_unit") or ""
    hc = cfg.get("healthcheck_url") or ""
    rel = f"{base}/releases/{version}"
    owner_script = recipe["script"] if recipe["kind"] == "script" else ""
    return f"""set -euo pipefail
umask 022
BASE={_q(base)}
REL={_q(rel)}
VERSION={_q(version)}
mkdir -p "$BASE/releases" "$BASE/shared" "$BASE/backups"
PREV=""
if [ -L "$BASE/current" ]; then PREV="$(basename "$(readlink "$BASE/current")")"; fi
echo "PREV=$PREV"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
tar czf "$BASE/backups/$TS-${{PREV:-empty}}.tar.gz" -C "$BASE" shared $( [ -n "$PREV" ] && echo "releases/$PREV" )
echo "BACKUP=$BASE/backups/$TS-${{PREV:-empty}}.tar.gz"
if [ -e "$REL" ]; then echo "Релиз $VERSION уже существует"; exit 3; fi
TMP="$REL.tmp.$$"
mkdir -p "$TMP"
tar xzf {_q(archive)} -C "$TMP"
rm -f {_q(archive)}
mv -T "$TMP" "$REL"
export NEXUS_RELEASE_DIR="$REL" NEXUS_BASE="$BASE" NEXUS_VERSION="$VERSION" NEXUS_SHARED="$BASE/shared"
cd "$REL"
{('( ' + chr(10) + owner_script + chr(10) + ' )') if owner_script else ':'}
ln -sfn "releases/$VERSION" "$BASE/current.new"
mv -T "$BASE/current.new" "$BASE/current"
echo "SWITCHED=$VERSION"
{f'sudo -n systemctl restart {_q(unit)}' if unit else ':'}
{f'for i in 1 2 3 4 5; do curl -fsS -m 10 {_q(hc)} >/dev/null && break; sleep 3; [ $i = 5 ] && exit 4; done' if hc else ':'}
set +o pipefail
ls -1t "$BASE/releases" | grep -v -x -F "$VERSION" | tail -n +{KEEP_RELEASES} | while read -r old; do [ -n "$old" ] && rm -rf -- "${{BASE:?}}/releases/${{old:?}}"; done
ls -1t "$BASE/backups" | tail -n +11 | while read -r old; do [ -n "$old" ] && rm -f -- "${{BASE:?}}/backups/${{old:?}}"; done
echo "OK"
"""


def remote_switch_script(base: str, target: str, unit: str = "") -> str:
    return f"""set -euo pipefail
BASE={_q(base)}
T={_q(target)}
[ -d "$BASE/releases/$T" ] || {{ echo "Нет релиза $T"; exit 2; }}
ln -sfn "releases/$T" "$BASE/current.new"
mv -T "$BASE/current.new" "$BASE/current"
{f'sudo -n systemctl restart {_q(unit)}' if unit else ':'}
echo "SWITCHED=$T"
"""


def _pack(src: Path) -> Path:
    import tarfile
    tmp = Path(tempfile.mkstemp(suffix=".tar.gz")[1])
    with tarfile.open(tmp, "w:gz") as tar:
        if src.is_dir():
            for p in sorted(src.iterdir()):
                tar.add(p, arcname=p.name)
        else:
            tar.add(src, arcname=src.name)
    return tmp


def deploy(portal, project: dict, env: str, version: str, source: Path, *, actor: str = "owner",
           automated: bool = False) -> dict:
    """Загрузить source (файл или каталог) как релиз version и атомарно переключить current."""
    if not VERSION_RE.match(version):
        raise DeployError("Некорректная версия")
    _check_allowed(portal, project, env, automated)
    recipe = active_recipe(portal, project, env)
    if not recipe:
        raise DeployError(f"Для окружения {env} не задан сценарий развёртывания")
    base = base_dir(portal, project, env)
    op = _op_start(portal, project, env, "deploy", version, recipe["id"])
    ex = portal.executor(project, env)
    archive_local = _pack(Path(source))
    remote_archive = f"{base}/incoming-{version}.tar.gz"
    log = f"Сценарий v{recipe['version']} sha256={recipe['sha256'][:12]} исполнитель={ex.name}\n"
    prev = ""
    try:
        ex.upload(archive_local, remote_archive)
        code, out = ex.run(remote_deploy_script(base, version, remote_archive, recipe))
        log += out
        prev = _grab(out, "PREV")
        backup = _grab(out, "BACKUP")
        if code != 0:
            if _grab(out, "SWITCHED") and prev:
                cfg = loads(recipe["config"], {})
                c2, o2 = ex.run(remote_switch_script(base, prev, cfg.get("systemd_unit") or ""))
                log += "\n--- автоматический откат ---\n" + o2
            _op_finish(portal, op, "failed", log, prev, backup)
            memory.add(portal.db, project["id"], "error", f"Деплой {env} {version} не удался", log[-2000:])
            notify(portal, f"Деплой {env} {version} не удался", "Выполнен откат к предыдущей версии." if prev else "",
                   "error", project["id"])
            raise DeployError(f"Развёртывание завершилось с кодом {code}")
        _op_finish(portal, op, "success", log, prev, backup)
    finally:
        archive_local.unlink(missing_ok=True)
    audit(portal.db, actor, "deploy", project["id"], {"env": env, "version": version, "previous": prev})
    notify(portal, f"Развёрнуто {env}: {version}", f"Предыдущая версия: {prev or 'нет'}", "success", project["id"])
    return portal.db.one("SELECT * FROM deploy_operations WHERE id=?", (op,))


def _grab(out: str, key: str) -> str:
    m = re.findall(rf"^{key}=(.*)$", out, re.M)
    return m[-1].strip() if m else ""


def list_remote_releases(portal, project: dict, env: str) -> dict:
    base = base_dir(portal, project, env)
    ex = portal.executor(project, env)
    code, out = ex.run(f"""set -e
BASE={_q(base)}
[ -L "$BASE/current" ] && echo "CURRENT=$(basename "$(readlink "$BASE/current")")" || true
[ -d "$BASE/releases" ] && ls -1t "$BASE/releases" | sed 's/^/R=/' || true
""")
    if code:
        raise DeployError(out[-500:])
    return {"current": _grab(out, "CURRENT"), "releases": re.findall(r"^R=(.*)$", out, re.M)}


def rollback(portal, project: dict, env: str, target: str | None = None, *, actor: str = "owner") -> dict:
    _check_allowed(portal, project, env, automated=False)
    state = list_remote_releases(portal, project, env)
    cur = state["current"]
    if target is None:
        older = [r for r in state["releases"] if r != cur]
        if not older:
            raise DeployError("Нет предыдущей версии для отката")
        target = older[0]
    if not VERSION_RE.match(target) or target not in state["releases"]:
        raise DeployError("Версия для отката не найдена")
    recipe = active_recipe(portal, project, env)
    unit = loads(recipe["config"], {}).get("systemd_unit", "") if recipe else ""
    op = _op_start(portal, project, env, "rollback", target)
    code, out = portal.executor(project, env).run(remote_switch_script(base_dir(portal, project, env), target, unit))
    _op_finish(portal, op, "success" if code == 0 else "failed", out, cur)
    if code:
        raise DeployError(out[-500:])
    audit(portal.db, actor, "rollback", project["id"], {"env": env, "from": cur, "to": target})
    notify(portal, f"Откат {env}: {cur} → {target}", "", "warning", project["id"])
    return portal.db.one("SELECT * FROM deploy_operations WHERE id=?", (op,))
