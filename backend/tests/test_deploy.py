import os
from pathlib import Path

import pytest

from backend.core import app_settings
from backend.deploy import service as deploy
from .conftest import make_project


def src(tmp_path, text, name="v"):
    d = tmp_path / f"src-{name}"
    d.mkdir()
    (d / "index.html").write_text(text)
    return d


def current(portal, p, env="dev"):
    base = Path(deploy.base_dir(portal, p, env))
    return (base / "current" / "index.html").read_text(), os.readlink(base / "current")


def test_deploy_rollback_cycle(portal, tmp_path):
    p = make_project(portal)
    deploy.save_recipe(portal, p, "dev", "static", {}, "")
    deploy.deploy(portal, p, "dev", "1.0.0", src(tmp_path, "v1", "a"))
    assert current(portal, p) == ("v1", "releases/1.0.0")
    op = deploy.deploy(portal, p, "dev", "1.1.0", src(tmp_path, "v2", "b"))
    assert op["status"] == "success" and op["previous_version"] == "1.0.0"
    assert op["backup_path"].endswith(".tar.gz") and Path(op["backup_path"]).exists()
    assert current(portal, p) == ("v2", "releases/1.1.0")
    deploy.rollback(portal, p, "dev")
    assert current(portal, p) == ("v1", "releases/1.0.0")
    st = deploy.list_remote_releases(portal, p, "dev")
    assert st["current"] == "1.0.0" and set(st["releases"]) == {"1.0.0", "1.1.0"}


def test_keeps_limited_releases(portal, tmp_path):
    p = make_project(portal)
    deploy.save_recipe(portal, p, "dev", "static", {}, "")
    for i in range(5):
        deploy.deploy(portal, p, "dev", f"1.0.{i}", src(tmp_path, f"v{i}", str(i)))
    rel = deploy.list_remote_releases(portal, p, "dev")["releases"]
    assert len(rel) == deploy.KEEP_RELEASES and "1.0.4" in rel


def test_script_recipe_and_failure_rollback(portal, tmp_path):
    p = make_project(portal)
    deploy.save_recipe(portal, p, "dev", "script", {}, 'echo "built $NEXUS_VERSION" > "$NEXUS_SHARED/log.txt"')
    deploy.deploy(portal, p, "dev", "1.0.0", src(tmp_path, "ok", "a"))
    base = Path(deploy.base_dir(portal, p, "dev"))
    assert (base / "shared" / "log.txt").read_text().strip() == "built 1.0.0"
    deploy.save_recipe(portal, p, "dev", "script", {}, "exit 7")
    with pytest.raises(deploy.DeployError):
        deploy.deploy(portal, p, "dev", "1.0.1", src(tmp_path, "bad", "b"))
    assert current(portal, p) == ("ok", "releases/1.0.0")  # переключения не было
    op = portal.db.one("SELECT * FROM deploy_operations ORDER BY id DESC LIMIT 1")
    assert op["status"] == "failed"
    assert portal.db.one("SELECT count(*) AS n FROM memory_entries WHERE kind='error'")["n"] == 1


def test_prod_requires_owner_permission(portal, tmp_path):
    p = make_project(portal)
    deploy.save_recipe(portal, p, "prod", "static", {}, "")
    with pytest.raises(deploy.DeployError, match="не разрешён"):
        deploy.deploy(portal, p, "prod", "1.0.0", src(tmp_path, "x"))
    portal.db.execute("UPDATE projects SET prod_deploy_allowed=1 WHERE id=?", (p["id"],))
    deploy.deploy(portal, portal.project(p["id"]), "prod", "1.0.0", src(tmp_path, "x", "y"))


def test_automated_deploy_respects_kill_switch(portal, tmp_path):
    p = make_project(portal)
    deploy.save_recipe(portal, p, "dev", "static", {}, "")
    app_settings.set_(portal.db, "global_kill_switch", True)
    with pytest.raises(deploy.DeployError, match="выключатель"):
        deploy.deploy(portal, p, "dev", "1.0.0", src(tmp_path, "x"), automated=True)


@pytest.mark.parametrize("cfg", [{"systemd_unit": "nginx.service"}, {"systemd_unit": "nexus-other-web.service"},
                                 {"systemd_unit": "nexus-game-x; rm -rf /.service"}, {"healthcheck_url": "file:///etc/passwd"}])
def test_foreign_services_rejected(portal, cfg):
    p = make_project(portal)
    with pytest.raises(deploy.DeployError):
        deploy.save_recipe(portal, p, "prod", "static", cfg, "")


def test_recipe_versioning(portal):
    p = make_project(portal)
    a = deploy.save_recipe(portal, p, "dev", "static", {"systemd_unit": "nexus-game-web.service"}, "")
    b = deploy.save_recipe(portal, p, "dev", "script", {}, "echo hi")
    assert (a["version"], b["version"]) == (1, 2) and a["sha256"] != b["sha256"]
    assert deploy.active_recipe(portal, p, "dev")["id"] == b["id"]


def test_invalid_inputs(portal, tmp_path):
    p = make_project(portal)
    with pytest.raises(deploy.DeployError):
        deploy.deploy(portal, p, "dev", "../../etc", src(tmp_path, "x"))
    with pytest.raises(deploy.DeployError):
        deploy.base_dir(portal, p, "staging")
    with pytest.raises(deploy.DeployError, match="сценарий"):
        deploy.deploy(portal, p, "dev", "1.0.0", src(tmp_path, "x", "z"))


def test_ssh_executor_requires_known_hosts(portal):
    from backend.deploy.executor import ExecError, SSHExecutor
    with pytest.raises(ExecError):
        SSHExecutor("1.2.3.4", "deploy", 22, None, None)


def test_deploy_api(authed, portal, tmp_path):
    p = make_project(portal)
    assert authed.put(f"/api/projects/{p['id']}/deploy/dev/recipe", json={"kind": "static"}).status_code == 200
    r = authed.post(f"/api/projects/{p['id']}/deploy/dev", data={"version": "2.0.0"},
                    files={"file": ("index.html", b"hello", "text/html")})
    assert r.status_code == 200, r.text
    ov = authed.get(f"/api/projects/{p['id']}/deploy").json()
    assert ov["recipes"]["dev"]["kind"] == "static" and ov["operations"][0]["version"] == "2.0.0"
    assert authed.post(f"/api/projects/{p['id']}/deploy/prod/rollback", json={}).status_code == 400
