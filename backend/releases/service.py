"""Релизы и APK: история версий, проверка, атомарная публикация на VPS, откат.

Каталог загрузок на VPS: {deploy_root}/{slug}/downloads/<version>/ и символическая ссылка latest.
"""
from __future__ import annotations

import shlex
import shutil
import tempfile
from pathlib import Path

from ..core import app_settings
from ..core.audit import audit
from ..deploy import service as deploy
from ..memory import service as memory
from ..notifications.service import notify
from .verify import ReleaseError, verify_artifact, write_release_dir

KEEP = 5  # опубликованных версий на диске (для отката)


def _q(s: str) -> str:
    return shlex.quote(s)


def downloads_dir(portal, project: dict) -> str:
    deploy.base_dir(portal, project, "prod")  # валидация slug и корня
    return f"{portal.settings.deploy_root.rstrip('/')}/{project['slug']}/downloads"


def download_url(portal, project: dict, version: str, file_name: str) -> str:
    base = portal.settings.public_download_base.rstrip("/")
    return f"{base}/{project['slug']}/{version}/{file_name}" if base else ""


def publish_script(base: str, version: str, archive: str) -> str:
    return f"""set -euo pipefail
umask 022
BASE={_q(base)}
V={_q(version)}
mkdir -p "$BASE"
if [ -e "$BASE/$V" ]; then echo "Версия $V уже опубликована"; exit 3; fi
TMP="$BASE/.tmp-$V-$$"
mkdir -p "$TMP"
tar xzf {_q(archive)} -C "$TMP"
rm -f -- {_q(archive)}
( cd "$TMP" && sha256sum -c SHA256SUMS )
mv -T "$TMP" "$BASE/$V"
PREV=""
if [ -L "$BASE/latest" ]; then PREV="$(readlink "$BASE/latest")"; fi
echo "PREV=$PREV"
ln -sfn "$V" "$BASE/latest.new"
mv -T "$BASE/latest.new" "$BASE/latest"
set +o pipefail
ls -1t "$BASE" | grep -v -x -e latest -e "$V" | grep -v '^[.]' | tail -n +{KEEP} | while read -r old; do
  if [ -n "$old" ]; then rm -r -- "${{BASE:?}}/${{old:?}}"; fi
done
echo "PUBLISHED=$V"
"""


def process_run(portal, project: dict, run: dict, gh=None, *, actor: str = "automation") -> dict:
    """Проверить и опубликовать артефакт успешного релизного запуска CI."""
    gh = gh or portal.github()
    repo = project["repo_full_name"]
    db = portal.db
    sha = run["head_sha"]
    if run.get("conclusion") != "success":
        raise ReleaseError("Релизный CI не завершился успешно")
    head_repo = (run.get("head_repository") or {}).get("full_name") or repo
    if head_repo.lower() != repo.lower():
        raise ReleaseError("Запуск из форка — публикация запрещена")
    if run.get("event") not in ("push", "release", "workflow_dispatch"):
        raise ReleaseError(f"Событие {run.get('event')} не является релизным")
    if run.get("head_branch") == project["default_branch"]:
        current = gh.branch_sha(repo, project["default_branch"])
        if current != sha:
            raise ReleaseError("SHA запуска не совпадает с актуальным SHA основной ветки — сборка устарела")
    elif run.get("event") == "push":
        raise ReleaseError("Релиз публикуется только из основной ветки или тега")
    if not project["release_artifact"]:
        raise ReleaseError("Имя релизного артефакта не задано в настройках проекта")
    arts = [a for a in gh.run_artifacts(repo, run["id"])
            if a["name"] == project["release_artifact"] and not a.get("expired")]
    if not arts:
        raise ReleaseError(f"Артефакт {project['release_artifact']!r} не найден в запуске {run['id']}")
    rel = verify_artifact(gh.download_artifact(repo, arts[0]["id"]), sha)
    if db.one("SELECT 1 AS x FROM releases WHERE project_id=? AND version=? AND status IN ('published','superseded')",
              (project["id"], rel.version)):
        return {"status": "exists", "version": rel.version}
    db.execute("DELETE FROM releases WHERE project_id=? AND version=? AND status NOT IN ('published','superseded')",
               (project["id"], rel.version))
    rid = db.insert("releases", {"project_id": project["id"], "version": rel.version,
                                 "version_code": rel.version_code, "channel": "release", "sha": sha,
                                 "run_id": run["id"], "artifact_name": arts[0]["name"],
                                 "file_name": rel.file_name, "sha256": rel.sha256, "size": rel.size,
                                 "status": "verified"})
    tmp = Path(tempfile.mkdtemp())
    try:
        write_release_dir(rel, tmp / "rel")
        archive = deploy._pack(tmp / "rel")
        base = downloads_dir(portal, project)
        ex = portal.executor(project, "prod")
        remote = f"{base}/.incoming-{rel.version}.tar.gz"
        try:
            ex.upload(archive, remote)
            code, out = ex.run(publish_script(base, rel.version, remote))
        finally:
            archive.unlink(missing_ok=True)
        if code != 0:
            raise ReleaseError("Публикация не удалась: " + out[-400:])
        url = download_url(portal, project, rel.version, rel.file_name)
        db.execute("UPDATE releases SET status='superseded' WHERE project_id=? AND status='published'", (project["id"],))
        db.execute("UPDATE releases SET status='published', download_url=?, published_at=datetime('now') WHERE id=?",
                   (url, rid))
        result = {"status": "published", "version": rel.version, "download_url": url}
        if project["prod_deploy_allowed"] and deploy.active_recipe(portal, project, "prod"):
            op = deploy.deploy(portal, project, "prod", rel.version, tmp / "rel", actor=actor, automated=True)
            result["deploy"] = op["status"]
    except Exception as e:
        db.execute("UPDATE releases SET status='failed', error=? WHERE id=? AND status!='published'",
                   (str(e)[:500], rid))
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    audit(db, actor, "release_published", project["id"], {"version": rel.version, "sha": sha, "sha256": rel.sha256})
    memory.add(db, project["id"], "task", f"Релиз {rel.version} опубликован",
               f"SHA {sha[:12]}, sha256 {rel.sha256[:16]}", result.get("download_url", ""))
    notify(portal, f"Опубликован релиз {rel.version}", result.get("download_url", ""), "success", project["id"])
    return result


def handle_workflow_run(portal, project: dict, run: dict) -> str:
    name = project.get("release_workflow") or ""
    if not name or (run.get("name") != name and not (run.get("path") or "").endswith(name)):
        return "not_release"
    if run.get("conclusion") != "success":
        notify(portal, f"Релизный CI завершился: {run.get('conclusion')}", run.get("html_url", ""), "error",
               project["id"])
        return "release_ci_failed"
    blocked = app_settings.automation_blocked(portal.db, project)
    if blocked or not project["auto_publish_releases"]:
        return "release_skipped"
    try:
        return "release_" + process_run(portal, project, run)["status"]
    except (ReleaseError, deploy.DeployError) as e:
        memory.add(portal.db, project["id"], "error", "Релиз не опубликован", str(e))
        notify(portal, "Релиз не опубликован", str(e), "error", project["id"])
        return "release_rejected"


def rollback(portal, project: dict, version: str, *, actor: str = "owner") -> dict:
    row = portal.db.one("SELECT * FROM releases WHERE project_id=? AND version=? AND status IN ('published','superseded')",
                        (project["id"], version))
    if not row:
        raise ReleaseError("Версия не найдена среди опубликованных")
    base = downloads_dir(portal, project)
    code, out = portal.executor(project, "prod").run(f"""set -euo pipefail
BASE={_q(base)}
V={_q(version)}
[ -d "$BASE/$V" ] || {{ echo "Файлы версии удалены с диска"; exit 2; }}
ln -sfn "$V" "$BASE/latest.new"
mv -T "$BASE/latest.new" "$BASE/latest"
echo OK
""")
    if code:
        raise ReleaseError(out[-400:])
    db = portal.db
    db.execute("UPDATE releases SET status='superseded' WHERE project_id=? AND status='published'", (project["id"],))
    db.execute("UPDATE releases SET status='published' WHERE id=?", (row["id"],))
    audit(db, actor, "release_rollback", project["id"], {"version": version})
    notify(portal, f"Релиз откатился на {version}", "", "warning", project["id"])
    return {"status": "ok", "latest": version}
