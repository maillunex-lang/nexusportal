"""Глобальные настройки в БД (без секретов) и аварийные выключатели."""
from __future__ import annotations

from typing import Any

from .db import Database, dumps, loads

DEFAULTS: dict[str, Any] = {
    "global_kill_switch": False,
    "notify_telegram_chat_id": "",
    "notify_max_chat_id": "",
    "notify_channels": ["portal"],
    "deploy_executor": "ssh",
    "ssh_host": "",
    "ssh_user": "",
    "ssh_port": 22,
    "allowed_repos": [],
}


def get(db: Database, key: str) -> Any:
    row = db.one("SELECT value FROM app_settings WHERE key=?", (key,))
    if row is None:
        return DEFAULTS.get(key)
    return loads(row["value"])


def set_(db: Database, key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise KeyError(key)
    db.execute(
        "INSERT INTO app_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, dumps(value)),
    )


def all_(db: Database) -> dict[str, Any]:
    return {k: get(db, k) for k in DEFAULTS}


def automation_blocked(db: Database, project: dict | None) -> str | None:
    """Вернуть причину блокировки автоматизации или None."""
    if get(db, "global_kill_switch"):
        return "Глобальный аварийный выключатель автоматизации включён"
    if project is not None and not project.get("automation_enabled"):
        return "Автоматизация проекта выключена"
    return None
