"""Точка входа NEXUS PORTAL: uvicorn backend.main:app"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from .api import auth, ops, projects
from .core.config import Settings, load_settings
from .core.db import Database
from .core.portal import Portal
from .core.redact import install_log_redaction

log = logging.getLogger("nexus")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; "
       "base-uri 'self'; form-action 'self'")


async def _sync_loop(portal: Portal) -> None:
    """Редкая резервная сверка с GitHub на случай потерянных webhook."""
    from .core import app_settings
    from .github import sync
    interval = portal.settings.sync_interval_minutes
    while True:
        await asyncio.sleep(interval * 60)
        if app_settings.get(portal.db, "global_kill_switch"):
            continue
        if not portal.settings.secret_status().get("github_token"):
            continue
        for pr in portal.db.all("SELECT * FROM projects WHERE archived=0 AND repo_full_name IS NOT NULL AND automation_enabled=1"):
            try:
                await asyncio.to_thread(sync.sync_project, portal, pr)
            except Exception as e:
                log.warning("Резервная сверка %s: %s", pr["slug"], e)


def create_app(settings: Settings | None = None, portal: Portal | None = None, background_sync: bool = True) -> FastAPI:
    settings = settings or (portal.settings if portal else load_settings())
    if portal is None:
        db = Database(settings.db_path)
        db.migrate()
        portal = Portal(settings, db)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    install_log_redaction()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        if background_sync and settings.sync_interval_minutes > 0:
            task = asyncio.create_task(_sync_loop(portal))
        yield
        if task:
            task.cancel()

    app = FastAPI(title="NEXUS PORTAL", version="1.0.0", lifespan=lifespan,
                  docs_url="/api/docs" if settings.dev_mode else None, redoc_url=None, openapi_url="/api/openapi.json" if settings.dev_mode else None)
    app.state.portal = portal

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.cookie_secure:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(ops.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "1.0.0", "journal_mode": portal.db.journal_mode()}

    dist = settings.frontend_dist
    if dist and Path(dist).is_dir():
        root = Path(dist).resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Не найдено"}, status_code=404)
            target = (root / path).resolve()
            if path and target.is_file() and root in target.parents:
                headers = {"Cache-Control": "no-cache"} if path in ("sw.js", "manifest.webmanifest") else {}
                return FileResponse(target, headers=headers)
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def _lazy_app():
    return create_app()


class _LazyASGI:
    """Приложение создаётся при первом обращении, чтобы импорт модуля не трогал диск."""
    _app = None

    async def __call__(self, scope, receive, send):
        if self._app is None:
            type(self)._app = create_app()
        await self._app(scope, receive, send)


app = _LazyASGI()
