import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import pytest

from backend.releases import service as releases
from backend.releases.verify import ReleaseError, verify_artifact
from .conftest import make_project, sign

SHA = "r" * 40


def apk(signed=True, debug=False) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("AndroidManifest.xml", "manifest")
        z.writestr("classes.dex", "dex")
        if signed:
            z.writestr("META-INF/CERT.RSA", b"cert CN=" + (b"Android Debug" if debug else b"Release Key"))
    return b.getvalue()


def artifact(content=None, file="game-1.2.0.apk", sha=SHA, channel="release", version="1.2.0", bad_sum=False) -> bytes:
    content = apk() if content is None else content
    digest = hashlib.sha256(content).hexdigest()
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("release.json", json.dumps({"version": version, "version_code": 10200, "channel": channel,
                                               "sha": sha, "file": file}))
        z.writestr("SHA256SUMS", f"{'0' * 64 if bad_sum else digest}  {file}\n")
        z.writestr(file, content)
    return b.getvalue()


def test_verify_ok():
    r = verify_artifact(artifact(), SHA)
    assert r.version == "1.2.0" and r.version_code == 10200 and len(r.sha256) == 64


@pytest.mark.parametrize("kw,msg", [
    ({"channel": "test"}, "тестовые"),
    ({"sha": "x" * 40}, "SHA"),
    ({"bad_sum": True}, "Контрольная"),
    ({"file": "game-debug.apk"}, "тестовую"),
    ({"content": apk(signed=False)}, "не подписан"),
    ({"content": apk(debug=True)}, "отладочным"),
    ({"version": "latest"}, "версия"),
    ({"file": "../evil.apk"}, "Недопустимое"),
])
def test_verify_rejects(kw, msg):
    with pytest.raises(ReleaseError, match=msg):
        verify_artifact(artifact(**kw), SHA)


def test_verify_rejects_garbage():
    with pytest.raises(ReleaseError):
        verify_artifact(b"nope", SHA)


def setup(portal, fake_gh, blob=None, **kw):
    fake_gh.add_repo("owner/game")
    fake_gh.branches[("owner/game", "main")] = SHA
    vals = dict(release_workflow="Release", release_artifact="release", auto_publish_releases=1)
    vals.update(kw)
    p = make_project(portal, **vals)
    run = {"id": 500, "name": "Release", "head_sha": SHA, "conclusion": "success", "event": "push",
           "head_branch": "main", "head_repository": {"full_name": "owner/game"}, "html_url": "u"}
    fake_gh.runs[500] = run
    fake_gh.artifacts[500] = [{"id": 9, "name": "release", "expired": False}]
    fake_gh.artifact_blobs[9] = blob or artifact()
    return p, run


def downloads(portal, p) -> Path:
    return Path(releases.downloads_dir(portal, p))


def test_auto_publish_on_release_ci(client, portal, fake_gh):
    p, run = setup(portal, fake_gh)
    body = json.dumps({"action": "completed", "workflow_run": run, "repository": {"full_name": "owner/game"}}).encode()
    r = client.post("/api/github/webhook", content=body, headers={
        "x-github-event": "workflow_run", "x-github-delivery": "rel1", "x-hub-signature-256": sign(body)})
    assert r.status_code == 200
    row = portal.db.one("SELECT * FROM releases")
    assert row["status"] == "published", row
    assert row["download_url"] == "https://dl.example.org/game/1.2.0/game-1.2.0.apk"
    d = downloads(portal, p)
    assert os.readlink(d / "latest") == "1.2.0"
    assert hashlib.sha256((d / "1.2.0" / "game-1.2.0.apk").read_bytes()).hexdigest() == row["sha256"]
    assert portal.db.one("SELECT * FROM webhook_deliveries WHERE delivery_id='rel1'")["status"] == "processed"


def test_stale_sha_not_published(portal, fake_gh):
    p, run = setup(portal, fake_gh)
    fake_gh.branches[("owner/game", "main")] = "n" * 40
    assert releases.handle_workflow_run(portal, p, run) == "release_rejected"
    assert portal.db.one("SELECT count(*) AS n FROM releases WHERE status='published'")["n"] == 0


def test_fork_and_pr_events_rejected(portal, fake_gh):
    p, run = setup(portal, fake_gh)
    with pytest.raises(ReleaseError):
        releases.process_run(portal, p, dict(run, event="pull_request"))
    with pytest.raises(ReleaseError):
        releases.process_run(portal, p, dict(run, head_repository={"full_name": "evil/fork"}))


def test_disabled_auto_publish_and_failed_ci(portal, fake_gh):
    p, run = setup(portal, fake_gh, auto_publish_releases=0)
    assert releases.handle_workflow_run(portal, p, run) == "release_skipped"
    assert releases.handle_workflow_run(portal, p, dict(run, conclusion="failure")) == "release_ci_failed"
    assert releases.handle_workflow_run(portal, p, dict(run, name="CI")) == "not_release"


def test_debug_build_rejected(portal, fake_gh):
    p, run = setup(portal, fake_gh, blob=artifact(content=apk(debug=True)))
    assert releases.handle_workflow_run(portal, p, run) == "release_rejected"
    assert not downloads(portal, p).exists() or not (downloads(portal, p) / "latest").exists()


def test_history_and_rollback(authed, portal, fake_gh):
    p, run = setup(portal, fake_gh)
    releases.process_run(portal, p, run)
    sha2 = "s" * 40
    fake_gh.branches[("owner/game", "main")] = sha2
    fake_gh.runs[501] = dict(run, id=501, head_sha=sha2)
    fake_gh.artifacts[501] = [{"id": 10, "name": "release", "expired": False}]
    fake_gh.artifact_blobs[10] = artifact(sha=sha2, version="1.3.0", file="game-1.3.0.apk")
    r = authed.post(f"/api/projects/{p['id']}/releases/process", json={"run_id": 501})
    assert r.status_code == 200 and r.json()["version"] == "1.3.0"
    assert os.readlink(downloads(portal, p) / "latest") == "1.3.0"
    hist = authed.get(f"/api/projects/{p['id']}/releases").json()
    assert [h["version"] for h in hist] == ["1.3.0", "1.2.0"]
    assert authed.post(f"/api/projects/{p['id']}/releases/1.2.0/rollback").status_code == 200
    assert os.readlink(downloads(portal, p) / "latest") == "1.2.0"
    # повторная обработка того же релиза идемпотентна
    assert releases.process_run(portal, p, fake_gh.runs[501])["status"] == "exists"


def test_release_also_deploys_when_allowed(portal, fake_gh):
    from backend.deploy import service as deploy
    p, run = setup(portal, fake_gh, prod_deploy_allowed=1)
    deploy.save_recipe(portal, p, "prod", "static", {}, "")
    res = releases.process_run(portal, p, run)
    assert res["deploy"] == "success"
    assert os.readlink(Path(deploy.base_dir(portal, p, "prod")) / "current") == "releases/1.2.0"
