"""Optional integration with feat/nexusportal-full-v1 after its separate review/merge."""
from .app import install
from .store import Store

def attach(app,db_path,github=None):
    from fastapi import Depends,Request
    from fastapi.responses import JSONResponse
    from backend.api import auth
    from backend.api.deps import require_owner
    def authorize(session=Depends(require_owner)):
        return {'actor':str(session.get('user_id','portal-owner')),'role':'owner'}
    # Reuse host credentials and host CSRF cookie; no second account store.
    @app.get('/api/blueprint/session')
    def session(s=Depends(require_owner)):
        return {'csrf':s['csrf_token'],'role':'owner'}
    @app.post('/api/blueprint/login')
    async def login(request:Request):
        from .app import data
        from backend.api.deps import client_ip
        from backend.core.security import SESSION_COOKIE
        from backend.core.audit import audit
        from fastapi import HTTPException
        p=request.app.state.portal;ip=client_ip(request)
        if auth.login_limiter.blocked(ip):raise HTTPException(429,'Слишком много попыток входа')
        d=await data(request)
        if not isinstance(d.get('username'),str) or not isinstance(d.get('password'),str):raise HTTPException(400,'Некорректные поля')
        if not p.auth.check_credentials(d['username'],d['password']):
            auth.login_limiter.hit(ip);raise HTTPException(401,'Неверные учётные данные')
        token,csrf=p.auth.create_session(ip,request.headers.get('user-agent',''))
        audit(p.db,'owner','blueprint_login',None,{},ip)
        response=JSONResponse({'csrf':csrf,'role':'owner'})
        response.set_cookie(SESSION_COOKIE,token,httponly=True,secure=p.settings.cookie_secure,samesite='strict',max_age=p.settings.session_ttl_hours*3600)
        return response
    from .github_adapter import ReadOnlyGitHub
    install(app,Store(db_path),authorize,ReadOnlyGitHub(github) if github else None)
