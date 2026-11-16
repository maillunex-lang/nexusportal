"""Проверка подписи GitHub Webhooks и дедупликация доставок."""
from __future__ import annotations

import hashlib
import hmac

from ..core.db import Database


def verify_signature(secret: str | None, body: bytes, header: str | None) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def register_delivery(db: Database, delivery_id: str, event: str, repo: str | None) -> bool:
    """True — новая доставка; False — повтор (уже обработана)."""
    cur = db.execute(
        "INSERT OR IGNORE INTO webhook_deliveries(delivery_id, event, repo) VALUES (?,?,?)",
        (delivery_id, event, repo),
    )
    return cur.rowcount == 1


def finish_delivery(db: Database, delivery_id: str, error: str | None = None) -> None:
    db.execute("UPDATE webhook_deliveries SET status=?, error=? WHERE delivery_id=?",
               ("error" if error else "processed", error, delivery_id))
