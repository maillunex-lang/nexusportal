from backend.core import app_settings
from backend.memory import service as memory
from backend.notifications import service as notifications
from .conftest import TOKEN, make_project


def test_memory_isolated_per_project(authed, portal):
    a = make_project(portal)
    b = make_project(portal, repo="owner/b", slug="bee")
    assert authed.post(f"/api/projects/{a['id']}/memory", json={"kind": "decision", "title": "Godot 4"}).status_code == 200
    assert authed.post(f"/api/projects/{a['id']}/memory", json={"kind": "bogus", "title": "x"}).status_code == 400
    assert len(authed.get(f"/api/projects/{a['id']}/memory").json()) == 1
    assert authed.get(f"/api/projects/{b['id']}/memory").json() == []
    eid = authed.get(f"/api/projects/{a['id']}/memory").json()[0]["id"]
    assert authed.delete(f"/api/projects/{b['id']}/memory/{eid}").status_code == 404
    assert authed.delete(f"/api/projects/{a['id']}/memory/{eid}").status_code == 200


def test_handover_prompt(authed, portal):
    a = make_project(portal)
    b = make_project(portal, repo="owner/b", slug="bee", name="Чужой")
    memory.add(portal.db, a["id"], "decision", "Движок Godot 4", f"token={TOKEN}")
    memory.add(portal.db, b["id"], "decision", "Секретное решение другого проекта")
    text = authed.get(f"/api/projects/{a['id']}/context").json()["prompt"]
    assert "Движок Godot 4" in text and "ИИ-директор" in text
    assert TOKEN not in text
    assert "другого проекта" not in text


def test_notifications_channels(portal, fake_gh, authed):
    portal.settings.write_secret("telegram_bot_token", "123456:" + "T" * 35)
    portal.settings.write_secret("max_bot_token", "max-token-value")
    app_settings.set_(portal.db, "notify_channels", ["portal", "telegram", "max"])
    app_settings.set_(portal.db, "notify_telegram_chat_id", "42")
    app_settings.set_(portal.db, "notify_max_chat_id", "77")
    p = make_project(portal)
    notifications.notify(portal, "Релиз", "1.0", "success", p["id"])
    assert fake_gh.telegram[0]["chat_id"] == "42" and "[Игра] Релиз" in fake_gh.telegram[0]["text"]
    assert fake_gh.max[0]["params"]["chat_id"] == "77" and fake_gh.max[0]["auth"] == "max-token-value"
    row = authed.get("/api/notifications").json()[0]
    assert row["title"] == "Релиз" and '"telegram": true' in row["delivered"]
    assert authed.post("/api/notifications/read-all").status_code == 200
    assert authed.get("/api/notifications?unread=true").json() == []


def test_notification_failure_does_not_break(portal):
    app_settings.set_(portal.db, "notify_channels", ["portal", "telegram"])
    nid = notifications.notify(portal, "x")  # токен не настроен — просто не доставлено
    assert '"telegram": false' in portal.db.one("SELECT delivered FROM notifications WHERE id=?", (nid,))["delivered"]
