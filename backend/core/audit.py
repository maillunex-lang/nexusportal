from __future__ import annotations

from .db import Database, dumps
from .redact import redact


def audit(db: Database, actor: str, action: str, project_id: int | None = None,
          detail: dict | None = None, ip: str = "") -> None:
    db.insert("audit_log", {
        "actor": actor,
        "action": action,
        "project_id": project_id,
        "detail": redact(dumps(detail or {})),
        "ip": ip,
    })
