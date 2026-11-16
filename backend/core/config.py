"""Конфигурация NEXUS PORTAL.

Обычные параметры берутся из переменных окружения ``NEXUS_*``.
Секреты (GitHub-токен, секрет webhook, токены Telegram/MAX) читаются только
из файлов в каталоге ``NEXUS_SECRETS_DIR`` с правами 0600 и никогда не
попадают в БД, логи или ответы API.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

SECRET_NAMES = (
    "github_token",
    "github_webhook_secret",
    "telegram_bot_token",
    "max_bot_token",
)


class SecretError(RuntimeError):
    pass


@dataclass
class Settings:
    data_dir: Path
    secrets_dir: Path
    db_path: Path
    cookie_secure: bool = True
    session_ttl_hours: int = 72
    allowed_origins: list[str] = field(default_factory=list)
    frontend_dist: Path | None = None
    sync_interval_minutes: int = 15
    github_api: str = "https://api.github.com"
    telegram_api: str = "https://api.telegram.org"
    max_api: str = "https://platform-api.max.ru"
    ssh_known_hosts: Path | None = None
    ssh_key_path: Path | None = None
    deploy_root: str = "/srv/nexus"
    public_download_base: str = ""
    dev_mode: bool = False

    def secret(self, name: str) -> str | None:
        """Прочитать секрет из файла. Отказ, если права шире 0600."""
        if name not in SECRET_NAMES:
            raise SecretError(f"Неизвестный секрет: {name}")
        path = self.secrets_dir / name
        if not path.exists():
            return None
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise SecretError(f"Файл секрета {name} должен иметь права 0600")
        value = path.read_text(encoding="utf-8").strip()
        return value or None

    def secret_status(self) -> dict[str, bool]:
        out = {}
        for name in SECRET_NAMES:
            try:
                out[name] = self.secret(name) is not None
            except SecretError:
                out[name] = False
        return out

    def write_secret(self, name: str, value: str) -> None:
        if name not in SECRET_NAMES:
            raise SecretError(f"Неизвестный секрет: {name}")
        self.secrets_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.secrets_dir, 0o700)
        path = self.secrets_dir / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value.strip() + "\n")
        os.chmod(path, 0o600)


def _bool(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("NEXUS_DATA_DIR", "./var")).resolve()
    secrets_dir = Path(os.environ.get("NEXUS_SECRETS_DIR", str(data_dir / "secrets"))).resolve()
    dist = os.environ.get("NEXUS_FRONTEND_DIST")
    default_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    kh = os.environ.get("NEXUS_SSH_KNOWN_HOSTS")
    key = os.environ.get("NEXUS_SSH_KEY")
    return Settings(
        data_dir=data_dir,
        secrets_dir=secrets_dir,
        db_path=Path(os.environ.get("NEXUS_DB", str(data_dir / "nexus.sqlite3"))).resolve(),
        cookie_secure=_bool(os.environ.get("NEXUS_COOKIE_SECURE"), True),
        session_ttl_hours=int(os.environ.get("NEXUS_SESSION_TTL_HOURS", "72")),
        allowed_origins=[o for o in os.environ.get("NEXUS_ALLOWED_ORIGINS", "").split(",") if o],
        frontend_dist=Path(dist) if dist else default_dist,
        sync_interval_minutes=int(os.environ.get("NEXUS_SYNC_INTERVAL_MINUTES", "15")),
        github_api=os.environ.get("NEXUS_GITHUB_API", "https://api.github.com"),
        telegram_api=os.environ.get("NEXUS_TELEGRAM_API", "https://api.telegram.org"),
        max_api=os.environ.get("NEXUS_MAX_API", "https://platform-api.max.ru"),
        ssh_known_hosts=Path(kh) if kh else None,
        ssh_key_path=Path(key) if key else None,
        deploy_root=os.environ.get("NEXUS_DEPLOY_ROOT", "/srv/nexus"),
        public_download_base=os.environ.get("NEXUS_PUBLIC_DOWNLOAD_BASE", ""),
        dev_mode=_bool(os.environ.get("NEXUS_DEV"), False),
    )
