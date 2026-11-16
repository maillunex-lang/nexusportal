import json

from backend.core import app_settings
from backend.orchestration import automerge
from backend.roadmap import service as roadmap
from .conftest import make_project, sign

SHA = "a" * 40
PLAN = {"project": "Игра", "stages": [], "tasks": [
    {"id": "A", "title": "Основа", "branch": "task/a"},
    {"id": "B", "title": "Меню", "depends_on": ["A"], "branch": "task/b"},
    {"id": "C", "title": "Звук", "depends_on": ["A"], "branch": "task/c"},
]}


def setup(portal, fake_gh, **kw):
    fake_gh.add_repo("owner/game")
    p = make_project(portal, **kw)
    roadmap.import_plan(portal.db, p, PLAN)
    fake_gh.add_pr("owner/game", 1, "task/a", SHA, "[A] Основа")
    return p


def status(portal, p, key):
    return roadmap.get_task(portal.db, p["id"], key)["status"]


def test_green_ci_merges_and_opens_next(portal, fake_gh):
    p = setup(portal, fake_gh)
    fake_gh.set_check("owner/game", SHA, "tests", "success")
    res = automerge.process_pr(portal, p, 1)
    assert res["decision"] == "merged", res
    assert fake_gh.merges == [{"repo": "owner/game", "number": 1, "sha": SHA}]
    assert status(portal, p, "A") == "done"
    assert status(portal, p, "B") == "ready" and status(portal, p, "C") == "ready"
    n = portal.db.all("SELECT title FROM notifications")
    assert any("A выполнена" in x["title"] for x in n)
    # идемпотентность
    assert automerge.process_pr(portal, p, 1)["decision"] == "merged"
    assert len(fake_gh.merges) == 1


def test_pending_waits(portal, fake_gh):
    p = setup(portal, fake_gh)
    fake_gh.set_check("owner/game", SHA, "tests", None, status="in_progress")
    res = automerge.process_pr(portal, p, 1)
    assert res["decision"] == "wait" and "не завершён" in " ".join(res["reasons"])
    assert status(portal, p, "A") == "in_progress"
    assert not fake_gh.merges


def test_failed_ci_blocks_and_builds_repair_prompt(portal, fake_gh):
    p = setup(portal, fake_gh)
    fake_gh.set_check("owner/game", SHA, "tests", "failure", run_id=99)
    res = automerge.process_pr(portal, p, 1)
    assert res["decision"] == "ci_failed"
    assert not fake_gh.merges
    t = roadmap.get_task(portal.db, p["id"], "A")
    assert t["status"] == "blocked" and "CI упал" in t["blocked_reason"]
    prompt = res["repair_prompt"]
    for needle in ("PR #1", "tests", "task/a", SHA, "pytest", "Задача A"):
        assert needle in prompt
    assert portal.db.one("SELECT count(*) AS n FROM memory_entries WHERE kind='error'")["n"] == 1
    # повтор не дублирует уведомления
    automerge.process_pr(portal, p, 1)
    assert portal.db.one("SELECT count(*) AS n FROM notifications WHERE level='error'")["n"] == 1
    # исправление: новый SHA, зелёный CI -> слияние
    new = "b" * 40
    fake_gh.prs[("owner/game", 1)]["head"]["sha"] = new
    fake_gh.set_check("owner/game", new, "tests", "success")
    assert automerge.process_pr(portal, p, 1)["decision"] == "merged"
    assert status(portal, p, "A") == "done"


def test_required_check_must_match_current_sha(portal, fake_gh):
    p = setup(portal, fake_gh)
    fake_gh.set_check("owner/game", "old" + "0" * 37, "tests", "success")  # зелёный, но для старого SHA
    assert automerge.process_pr(portal, p, 1)["decision"] == "wait"
    assert not fake_gh.merges


def test_other_checks_not_enough(portal, fake_gh):
    p = setup(portal, fake_gh)
    fake_gh.set_check("owner/game", SHA, "lint", "success")
    assert automerge.process_pr(portal, p, 1)["decision"] == "wait"


def test_branch_protection_checks_added(portal, fake_gh):
    p = setup(portal, fake_gh)
    fake_gh.protection[("owner/game", "main")] = ["build"]
    fake_gh.set_check("owner/game", SHA, "tests", "success")
    assert automerge.process_pr(portal, p, 1)["decision"] == "wait"
    fake_gh.set_check("owner/game", SHA, "build", "success")
    assert automerge.process_pr(portal, p, 1)["decision"] == "merged"


def test_no_required_checks_blocks(portal, fake_gh):
    p = setup(portal, fake_gh, required_checks="[]")
    fake_gh.set_check("owner/game", SHA, "tests", "success")
    res = automerge.process_pr(portal, p, 1)
    assert res["decision"] == "wait" and any("обязательные проверки" in r for r in res["reasons"])


def test_kill_switches(portal, fake_gh):
    p = setup(portal, fake_gh)
    fake_gh.set_check("owner/game", SHA, "tests", "success")
    app_settings.set_(portal.db, "global_kill_switch", True)
    assert automerge.process_pr(portal, p, 1)["decision"] == "wait"
    app_settings.set_(portal.db, "global_kill_switch", False)
    portal.db.execute("UPDATE projects SET automation_enabled=0 WHERE id=?", (p["id"],))
    assert automerge.process_pr(portal, portal.project(p["id"]), 1)["decision"] == "wait"
    assert not fake_gh.merges


def test_auto_merge_disabled(portal, fake_gh):
    p = setup(portal, fake_gh, auto_merge_enabled=0)
    fake_gh.set_check("owner/game", SHA, "tests", "success")
    assert automerge.process_pr(portal, p, 1)["decision"] == "wait"


def test_fork_and_unlinked_pr_refused(portal, fake_gh):
    p = setup(portal, fake_gh)
    fake_gh.add_pr("owner/game", 2, "task/b", "c" * 40, "[B] меню", fork=True)
    fake_gh.set_check("owner/game", "c" * 40, "tests", "success")
    res = automerge.process_pr(portal, p, 2)
    assert res["decision"] == "wait" and any("форк" in r for r in res["reasons"])
    fake_gh.add_pr("owner/game", 3, "random", "d" * 40, "без задачи")
    fake_gh.set_check("owner/game", "d" * 40, "tests", "success")
    assert automerge.process_pr(portal, p, 3)["decision"] == "wait"
    assert not fake_gh.merges


def test_conflicts_block(portal, fake_gh):
    p = setup(portal, fake_gh)
    fake_gh.prs[("owner/game", 1)]["mergeable"] = False
    fake_gh.set_check("owner/game", SHA, "tests", "success")
    assert automerge.process_pr(portal, p, 1)["decision"] == "wait"


def test_merge_rejected_when_sha_moves(portal, fake_gh, monkeypatch):
    p = setup(portal, fake_gh)
    fake_gh.set_check("owner/game", SHA, "tests", "success")
    orig = fake_gh.__call__

    def racing(req):
        if req.url.path.endswith("/merge"):
            fake_gh.prs[("owner/game", 1)]["head"]["sha"] = "z" * 40
        return orig(req)
    portal.http_transport.handler = racing
    res = automerge.process_pr(portal, p, 1)
    assert res["decision"] == "merge_rejected"
    assert status(portal, p, "A") == "in_progress"


def test_webhook_end_to_end(client, portal, fake_gh):
    p = setup(portal, fake_gh)
    fake_gh.set_check("owner/game", SHA, "tests", "success")
    payload = {"action": "completed", "check_suite": {"head_sha": SHA}, "repository": {"full_name": "owner/game"}}
    portal.db.execute("UPDATE pull_requests SET head_sha=? WHERE 1", (SHA,))
    automerge.sync.upsert_pr(portal, p, fake_gh.prs[("owner/game", 1)])
    body = json.dumps(payload).encode()
    r = client.post("/api/github/webhook", content=body, headers={
        "x-github-event": "check_suite", "x-github-delivery": "e2e", "x-hub-signature-256": sign(body)})
    assert r.status_code == 200
    assert fake_gh.merges and status(portal, p, "A") == "done"


def test_merged_webhook_marks_done(client, portal, fake_gh):
    p = setup(portal, fake_gh, auto_merge_enabled=0)
    automerge.sync.upsert_pr(portal, p, fake_gh.prs[("owner/game", 1)])
    pr = dict(fake_gh.prs[("owner/game", 1)], state="closed", merged=True, merge_commit_sha="f" * 40)
    body = json.dumps({"action": "closed", "pull_request": pr, "repository": {"full_name": "owner/game"}}).encode()
    client.post("/api/github/webhook", content=body, headers={
        "x-github-event": "pull_request", "x-github-delivery": "m1", "x-hub-signature-256": sign(body)})
    assert status(portal, p, "A") == "done"
    assert status(portal, p, "B") == "ready"


def test_sync_fallback(authed, portal, fake_gh):
    p = setup(portal, fake_gh)
    fake_gh.set_check("owner/game", SHA, "tests", "success")
    r = authed.post(f"/api/projects/{p['id']}/sync")
    assert r.status_code == 200 and r.json()["decisions"][0]["decision"] == "merged"
    assert authed.get(f"/api/projects/{p['id']}/merge-log").json()[0]["decision"] == "merge"
    assert authed.get("/api/dashboard").status_code == 200
