from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from ..core.security import CSRF_HEADER, SESSION_COOKIE


def portal(request: Request):
    return request.app.state.portal


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def require_owner(request: Request, p=Depends(portal)) -> dict:
    sess = p.auth.get_session(request.cookies.get(SESSION_COOKIE))
    if not sess:
        raise HTTPException(401, "Требуется вход")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not p.auth.csrf_ok(sess, request.headers.get(CSRF_HEADER)):
            raise HTTPException(403, "Неверный CSRF-токен")
    return sess


def get_project(project_id: int, p=Depends(portal), _=Depends(require_owner)) -> dict:
    pr = p.project(project_id)
    if not pr:
        raise HTTPException(404, "Проект не найден")
    return pr
