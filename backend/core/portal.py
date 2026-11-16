"""Контейнер зависимостей портала (настройки, БД, клиенты интеграций)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import httpx

from . import app_settings
from .config import Settings
from .db import Database
from .security import Auth


@dataclass
class Portal:
    settings: Settings
    db: Database
    http_transport: httpx.BaseTransport | None = None  # подменяется в тестах
    executor_factory: Callable | None = None           # подменяется в тестах
    auth: Auth = field(init=False)

    def __post_init__(self):
        self.auth = Auth(self.db, self.settings.session_ttl_hours)

    def github(self):
        from ..github.client import GitHubClient
        return GitHubClient(self.settings.secret("github_token"), self.settings.github_api,
                            transport=self.http_transport,
                            allowed_repos=app_settings.get(self.db, "allowed_repos") or None)

    def http(self) -> httpx.Client:
        return httpx.Client(timeout=20, transport=self.http_transport)

    def executor(self, project: dict, env: str):
        if self.executor_factory:
            return self.executor_factory(self, project, env)
        from ..deploy.executor import make_executor
        return make_executor(self, project, env)

    def project(self, project_id: int) -> dict | None:
        return self.db.one("SELECT * FROM projects WHERE id=?", (project_id,))

    def project_by_repo(self, repo: str) -> dict | None:
        return self.db.one("SELECT * FROM projects WHERE lower(repo_full_name)=lower(?) AND archived=0", (repo,))
