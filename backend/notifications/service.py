"""Уведомления: внутри портала, Telegram и MAX."""
from __future__ import annotations

import logging

from ..core import app_settings
from ..core.db import dumps
from ..core.redact import redact

log = logging.getLogger("nexus.notify")
LEVELS = ("info", "success", "warning", "error")


def notify(portal, title: str, body: str = "", level: str = "info", project_id: int | None = None) -> int:
    if level not in LEVELS:
        level = "info"
    title, body = redact(title)[:300], redact(body)[:4000]
    nid = portal.db.insert("notifications", {"project_id": project_id, "level": level,
                                             "title": title, "body": body})
    channels = app_settings.get(portal.db, "notify_channels") or []
    delivered = {"portal": True}
    project = portal.project(project_id) if project_id else None
    text = f"{'[' + project['name'] + '] ' if project else ''}{title}\n{body}".strip()
    if "telegram" in channels:
        delivered["telegram"] = _safe(send_telegram, portal, text)
    if "max" in channels:
        delivered["max"] = _safe(send_max, portal, text)
    portal.db.execute("UPDATE notifications SET delivered=? WHERE id=?", (dumps(delivered), nid))
    return nid


def _safe(fn, portal, text) -> bool:
    try:
        return fn(portal, text)
    except Exception as e:  # уведомление не должно ломать основной поток
        log.warning("Не удалось отправить уведомление: %s", redact(str(e)))
        return False


def send_telegram(portal, text: str) -> bool:
    token = portal.settings.secret("telegram_bot_token")
    chat = app_settings.get(portal.db, "notify_telegram_chat_id")
    if not token or not chat:
        return False
    with portal.http() as http:
        r = http.post(f"{portal.settings.telegram_api}/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True})
    return r.status_code == 200 and r.json().get("ok") is True


def send_max(portal, text: str) -> bool:
    """MAX Bot API: POST /messages?chat_id=... с заголовком Authorization: <token>."""
    token = portal.settings.secret("max_bot_token")
    chat = app_settings.get(portal.db, "notify_max_chat_id")
    if not token or not chat:
        return False
    with portal.http() as http:
        r = http.post(f"{portal.settings.max_api}/messages", params={"chat_id": chat},
                      headers={"Authorization": token}, json={"text": text[:4000]})
    return 200 <= r.status_code < 300


def list_(db, unread_only: bool = False, limit: int = 100) -> list[dict]:
    q = "SELECT * FROM notifications" + (" WHERE is_read=0" if unread_only else "") + " ORDER BY id DESC LIMIT ?"
    return db.all(q, (limit,))
