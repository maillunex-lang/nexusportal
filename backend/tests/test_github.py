import json
import logging

from .conftest import TOKEN, make_project, sign


def post_hook(client, event, payload, delivery="d1", secret=None):
    body = json.dumps(payload).encode()
    headers = {"x-github-event": event, "x-github-delivery": delivery,
               "x-hub-signature-256": sign(body) if secret is None else secret, "content-type": "application/json"}
    return client.post("/api/github/webhook", content=body, headers=headers)


def test_webhook_signature_required(client, portal):
    make_project(portal)
    assert post_hook(client, "ping", {"repository": {"full_name": "owner/game"}}, secret="sha256=00").status_code == 401
    assert post_hook(client, "ping", {"repository": {"full_name": "owner/game"}}, secret="").status_code == 401
    r = post_hook(client, "ping", {"repository": {"full_name": "owner/game"}})
    assert r.status_code == 200 and r.json()["status"] == "accepted"


def test_webhook_deduplicated(client, portal):
    make_project(portal)
    assert post_hook(client, "ping", {"repository": {"full_name": "owner/game"}}, "same").json()["status"] == "accepted"
    assert post_hook(client, "ping", {"repository": {"full_name": "owner/game"}}, "same").json()["status"] == "duplicate"
    row = portal.db.one("SELECT * FROM webhook_deliveries WHERE delivery_id='same'")
    assert row["status"] == "processed"


def test_webhook_tracks_pr_and_commits(client, portal, fake_gh):
    fake_gh.add_repo("owner/game")
    make_project(portal, auto_merge_enabled=0)
    pr = fake_gh.add_pr("owner/game", 5, "task/a", "s" * 40, "[A] задача")
    assert post_hook(client, "pull_request", {"action": "opened", "pull_request": pr,
                                              "repository": {"full_name": "owner/game"}}).status_code == 200
    row = portal.db.one("SELECT * FROM pull_requests WHERE number=5")
    assert row["head_sha"] == "s" * 40 and row["state"] == "open"
    post_hook(client, "push", {"ref": "refs/heads/main", "repository": {"full_name": "owner/game"},
                               "commits": [{"id": "abc", "message": "fix", "author": {"name": "dev"}}]}, "d2")
    assert portal.db.one("SELECT * FROM commits WHERE sha='abc'")["message"] == "fix"


def test_unknown_repo_ignored(client, portal):
    r = post_hook(client, "ping", {"repository": {"full_name": "other/repo"}})
    assert r.status_code == 200


def test_token_only_on_server(portal, fake_gh, caplog):
    fake_gh.add_repo("owner/game")
    gh = portal.github()
    with caplog.at_level(logging.INFO):
        logging.getLogger("t").info("calling with %s", TOKEN)
    gh.repo("owner/game")
    assert f"Bearer {TOKEN}" in fake_gh.auth_seen
    assert TOKEN not in caplog.text


def test_allowed_repos_enforced(portal, fake_gh):
    from backend.core import app_settings
    from backend.github.client import GitHubError
    fake_gh.add_repo("owner/game")
    app_settings.set_(portal.db, "allowed_repos", ["owner/other"])
    try:
        portal.github().repo("owner/game")
        raise AssertionError("должно быть запрещено")
    except GitHubError as e:
        assert e.status == 403


def test_github_status(authed, fake_gh):
    s = authed.get("/api/github/status").json()
    assert s["token_configured"] and s["login"] == "owner"
    assert TOKEN not in json.dumps(s)
