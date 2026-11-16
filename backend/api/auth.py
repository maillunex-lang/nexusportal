from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..core.audit import audit
from ..core.security import SESSION_COOKIE, RateLimiter
from .deps import client_ip, portal, require_owner

router = APIRouter(prefix="/api/auth")
login_limiter = RateLimiter(limit=5, window_s=300)


class LoginIn(BaseModel):
    username: str
    password: str


@router.get("/status")
def status(request: Request, p=Depends(portal)):
    sess = p.auth.get_session(request.cookies.get(SESSION_COOKIE))
    return {"owner_exists": p.auth.owner_exists(), "authenticated": bool(sess),
            "csrf_token": sess["csrf_token"] if sess else None}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, p=Depends(portal)):
    ip = client_ip(request)
    if login_limiter.blocked(ip):
        raise HTTPException(429, "Слишком много попыток входа. Подождите 5 минут.")
    if not p.auth.check_credentials(body.username, body.password):
        login_limiter.hit(ip)
        audit(p.db, "anonymous", "login_failed", None, {"username": body.username[:50]}, ip)
        raise HTTPException(401, "Неверный логин или пароль")
    token, csrf = p.auth.create_session(ip, request.headers.get("user-agent", ""))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=p.settings.cookie_secure,
                        samesite="strict", max_age=p.settings.session_ttl_hours * 3600, path="/")
    audit(p.db, "owner", "login", None, {}, ip)
    return {"ok": True, "csrf_token": csrf}


@router.post("/logout")
def logout(request: Request, response: Response, p=Depends(portal), _=Depends(require_owner)):
    p.auth.destroy(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    audit(p.db, "owner", "logout", None, {}, client_ip(request))
    return {"ok": True}
