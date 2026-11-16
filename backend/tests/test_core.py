import logging
import os
import sqlite3

import pytest

from backend.core import app_settings
from backend.core.config import SecretError
from backend.core.db import Database, verify_backup
from backend.core.redact import RedactingFilter, redact
from backend.core.security import hash_password, verify_password
from .conftest import TOKEN


def test_migrations_idempotent_and_wal(tmp_path):
    db = Database(tmp_path / "x.sqlite3")
    applied = db.migrate()
    assert applied == ["0001_init"]
    assert db.migrate() == []
    assert db.journal_mode() == "wal"
    tables = {r["name"] for r in db.all("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("projects", "tasks", "pull_requests", "releases", "memory_entries", "notifications",
              "deploy_operations", "webhook_deliveries", "audit_log", "sessions"):
        assert t in tables


def test_task_status_constraint(portal):
    from .conftest import make_project
    p = make_project(portal)
    with pytest.raises(sqlite3.IntegrityError):
        portal.db.execute("INSERT INTO tasks(project_id, task_key, title, status) VALUES (?,?,?,?)", (p["id"], "X", "x", "bogus"))


def test_backup_and_verify(portal, tmp_path):
    dest = portal.db.backup(tmp_path / "b" / "copy.sqlite3")
    verify_backup(dest)
    bad = tmp_path / "bad.sqlite3"
    bad.write_bytes(b"not a db" * 100)
    with pytest.raises(Exception):
        verify_backup(bad)


def test_password_hashing():
    h = hash_password("very-long-password")
    assert verify_password("very-long-password", h)
    assert not verify_password("wrong-password!!", h)
    with pytest.raises(ValueError):
        hash_password("short")


def test_secret_requires_0600(portal):
    path = portal.settings.secrets_dir / "github_token"
    os.chmod(path, 0o644)
    with pytest.raises(SecretError):
        portal.settings.secret("github_token")
    os.chmod(path, 0o600)
    assert portal.settings.secret("github_token") == TOKEN


def test_redaction():
    text = f"token={TOKEN} and ghp_{'b'*36} 123456789:{'A'*35}"
    out = redact(text)
    assert TOKEN not in out and "ghp_bbbb" not in out and "AAAAAAAAAA" not in out
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "Authorization: Bearer %s", (TOKEN,), None)
    RedactingFilter().filter(rec)
    assert TOKEN not in rec.getMessage()


def test_auth_flow_and_csrf(client):
    assert client.get("/api/dashboard").status_code == 401
    st = client.get("/api/auth/status").json()
    assert st == {"owner_exists": True, "authenticated": False, "csrf_token": None}
    assert client.post("/api/auth/login", json={"username": "owner", "password": "nope-nope-nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "owner", "password": "correct horse battery"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    csrf = r.json()["csrf_token"]
    assert client.get("/api/dashboard").status_code == 200
    # изменение без CSRF запрещено
    assert client.put("/api/settings", json={"values": {"global_kill_switch": True}}).status_code == 403
    assert client.put("/api/settings", json={"values": {"global_kill_switch": True}},
                      headers={"x-csrf-token": "wrong"}).status_code == 403
    r = client.put("/api/settings", json={"values": {"global_kill_switch": True}}, headers={"x-csrf-token": csrf})
    assert r.status_code == 200 and r.json()["global_kill_switch"] is True
    assert client.post("/api/auth/logout", headers={"x-csrf-token": csrf}).status_code == 200
    assert client.get("/api/dashboard").status_code == 401


def test_login_rate_limited(client):
    from backend.api import auth
    auth.login_limiter.hits.clear()
    codes = [client.post("/api/auth/login", json={"username": "owner", "password": "bad-password-x"}).status_code
             for _ in range(7)]
    assert codes[-1] == 429
    auth.login_limiter.hits.clear()


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.json()["journal_mode"] == "wal"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


def test_settings_never_return_secrets(authed, portal):
    r = authed.put("/api/settings/secrets/telegram_bot_token", json={"value": "123456:" + "Z" * 35})
    assert r.status_code == 200
    s = authed.get("/api/settings").json()
    assert s["secrets"]["telegram_bot_token"] is True
    assert "ZZZZZ" not in authed.get("/api/settings").text
    assert TOKEN not in authed.get("/api/github/status").text
    mode = os.stat(portal.settings.secrets_dir / "telegram_bot_token").st_mode & 0o777
    assert mode == 0o600
    audit = authed.get("/api/audit").text
    assert "ZZZZZ" not in audit


def test_settings_validation(authed):
    assert authed.put("/api/settings", json={"values": {"unknown": 1}}).status_code == 400
    assert authed.put("/api/settings", json={"values": {"notify_channels": ["sms"]}}).status_code == 400
    assert authed.put("/api/settings", json={"values": {"deploy_executor": "local"}}).status_code == 200


def test_kill_switch_helper(portal):
    from .conftest import make_project
    p = make_project(portal)
    assert app_settings.automation_blocked(portal.db, p) is None
    portal.db.execute("UPDATE projects SET automation_enabled=0 WHERE id=?", (p["id"],))
    assert "проекта" in app_settings.automation_blocked(portal.db, portal.project(p["id"]))
    app_settings.set_(portal.db, "global_kill_switch", True)
    assert "Глобальный" in app_settings.automation_blocked(portal.db, p)


def test_cli_migrate_and_owner(tmp_path, monkeypatch, capsys):
    from backend import cli
    monkeypatch.setenv("NEXUS_DATA_DIR", str(tmp_path))
    assert cli.main(["migrate"]) == 0
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("a-very-strong-pass\n"))
    assert cli.main(["set-owner", "admin"]) == 0
    assert cli.main(["backup"]) == 0
    assert "проверена" in capsys.readouterr().out
