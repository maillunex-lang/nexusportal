"""Standalone ASGI app plus router factory for the existing portal auth/GitHub client."""
from __future__ import annotations
import argparse
import getpass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
from fastapi import APIRouter,Depends,FastAPI,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.routing import APIRoute
from .engine import MAX_BYTES
from .store import Store,Conflict

STATIC=Path(__file__).parent/'static'

def password_hash(password,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+':'+hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()

def check_password(password,encoded):
    return hmac.compare_digest(password_hash(password,encoded.split(':')[0]),encoded)

async def body(request,limit=MAX_BYTES):
    chunks=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>limit:raise HTTPException(413,'Превышен размер файла')
        chunks.append(chunk)
    return b''.join(chunks)

async def data(request):
    try:d=json.loads(await body(request))
    except (ValueError,UnicodeError):raise HTTPException(400,'Некорректный JSON')
    if not isinstance(d,dict):raise HTTPException(400,'Ожидался объект')
    return d

def router(store,authorize,github=None):
    """authorize must enforce session, CSRF, role and return {actor, role}."""
    class BlueprintRoute(APIRoute):
        def get_route_handler(self):
            original=super().get_route_handler()
            async def handler(request):
                try:return await original(request)
                except Conflict as e:return JSONResponse({'detail':str(e)},status_code=409)
                except PermissionError as e:return JSONResponse({'detail':str(e)},status_code=403)
                except (ValueError,TypeError,KeyError) as e:
                    return JSONResponse({'detail':str(e) if isinstance(e,ValueError) else 'Некорректные поля запроса'},status_code=400)
            return handler
    r=APIRouter(prefix='/api/blueprint',dependencies=[Depends(authorize)],route_class=BlueprintRoute)
    def writer(user,owner=False):
        if user.get('role') not in ({'owner'} if owner else {'owner','executor'}):raise HTTPException(403,'Недостаточно прав')
    @r.get('/versions')
    def versions():return store.versions()
    @r.post('/import')
    async def import_plan(request:Request,user=Depends(authorize)):
        writer(user,True)
        return {'version':store.import_plan(await body(request),user['actor'])}
    @r.get('/versions/{version}')
    def preview(version:int):
        with store.connection() as db:return store.preview(db,version)
    @r.post('/versions/{version}/approve')
    async def approve(version:int,request:Request,user=Depends(authorize)):
        writer(user,True);d=await data(request)
        if 'expected_version' not in d:raise ValueError('Нужна текущая версия')
        if type(d.get('ack_active',False)) is not bool or not isinstance(d.get('reset_ids',[]),list):raise ValueError('Неверное подтверждение')
        store.approve(version,user['actor'],d['expected_version'],d.get('reset_ids',[]),d.get('ack_active',False))
        return {'ok':True}
    @r.get('/projects/{project}')
    def snapshot(project:str):return store.snapshot(project)
    @r.get('/projects/{project}/history')
    def history(project:str):return store.history(project)
    @r.post('/projects/{project}/tasks/{tid}/review')
    async def review(project:str,tid:str,request:Request,user=Depends(authorize)):
        writer(user,True);d=await data(request)
        store.review(project,tid,user['actor'],d.get('version'),d.get('note',''),d.get('scopes'))
        return {'ok':True}
    @r.get('/projects/{project}/tasks/{tid}/prompt')
    def prompt(project:str,tid:str,version:int):
        sha=None
        if github is not None:
            plan=store.snapshot(project)['plan']
            try:
                candidate=github.branch_sha(plan['project']['repository'],plan['project']['base_branch'])
                import re
                if re.fullmatch('[0-9a-f]{40}',candidate):sha=candidate
            except Exception:pass  # Offline/manual mode never invents a SHA.
        return {'prompt':store.prompt(project,tid,version,sha)}
    @r.post('/projects/{project}/tasks/{tid}/dispatch')
    async def dispatch(project:str,tid:str,request:Request,user=Depends(authorize)):
        writer(user);d=await data(request)
        sha=None
        if github is not None:
            plan=store.snapshot(project)['plan']
            try:
                from starlette.concurrency import run_in_threadpool
                candidate=await run_in_threadpool(github.branch_sha,plan['project']['repository'],plan['project']['base_branch'])
                import re
                if re.fullmatch('[0-9a-f]{40}',candidate):sha=candidate
            except Exception:pass
        return {'prompt':store.dispatch(project,tid,user['actor'],d.get('version'),sha)}
    @r.post('/projects/{project}/tasks/{tid}/status')
    async def status(project:str,tid:str,request:Request,user=Depends(authorize)):
        writer(user);d=await data(request)
        store.transition(project,tid,d.get('status'),user['actor'],user['role'],d.get('version'),d.get('expected_status'),
                         d.get('note',''),d.get('executor',''),d.get('pr'),d.get('evidence'))
        return {'ok':True}
    @r.post('/projects/{project}/tasks/{tid}/github')
    async def sync(project:str,tid:str,request:Request,user=Depends(authorize)):
        writer(user);d=await data(request)
        if github is None:raise HTTPException(503,'GitHub не подключён. Доступно ручное обновление.')
        # Network operation runs outside the ASGI event loop.
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(store.github_sync,project,tid,user['actor'],d.get('version'),github)
    return r

def install(app,store,authorize,github=None):
    """Call before the portal SPA catch-all route. Existing middleware/auth remain authoritative."""
    app.include_router(router(store,authorize,github))
    app.mount('/blueprint/assets',StaticFiles(directory=STATIC),name='blueprint-assets')
    @app.get('/blueprint',include_in_schema=False)
    def page():return FileResponse(STATIC/'index.html')
    @app.exception_handler(Conflict)
    async def conflict(request,error):return JSONResponse({'detail':str(error)},status_code=409)
    # Only blueprint exceptions are wrapped; no global ValueError handler in host application.

def create_app(db_path,users,secure_cookie=True,github=None):
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    store=Store(db_path);sessions={};attempts={}
    app.state.blueprint=store
    async def authorize(request:Request):
        token=request.cookies.get('bp_session');s=sessions.get(token)
        if not s or s['expires']<time.time():raise HTTPException(401,'Требуется вход')
        if request.method not in ('GET','HEAD','OPTIONS') and not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),s['csrf']):raise HTTPException(403,'Неверный CSRF-токен')
        return s
    @app.middleware('http')
    async def security(request,call_next):
        try:resp=await call_next(request)
        except Conflict as e:resp=JSONResponse({'detail':str(e)},status_code=409)
        except (ValueError,TypeError,KeyError) as e:
            resp=JSONResponse({'detail':str(e) if isinstance(e,ValueError) else 'Некорректные поля запроса'},status_code=400)
        except PermissionError as e:resp=JSONResponse({'detail':str(e)},status_code=403)
        resp.headers.update({'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Cache-Control':'no-store'})
        return resp
    @app.post('/api/blueprint/login')
    async def login(request:Request):
        ip=request.client.host if request.client else 'local';now=time.time()
        recent=[t for t in attempts.get(ip,[]) if now-t<60];attempts[ip]=recent
        if len(recent)>=8:raise HTTPException(429,'Повторите вход через минуту')
        recent.append(now);d=await data(request);u=users.get(d.get('username',''))
        password=d.get('password','')
        if not isinstance(password,str) or len(password)>1024:raise HTTPException(400,'Некорректный пароль')
        if not u or not check_password(password,u['hash']):raise HTTPException(401,'Неверные учётные данные')
        token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
        sessions[token]={'actor':d['username'],'role':u['role'],'csrf':csrf,'expires':now+8*3600}
        with store.transaction() as db:store.event(db,'*',d['username'],'login',{})
        resp=JSONResponse({'csrf':csrf,'role':u['role']})
        resp.set_cookie('bp_session',token,httponly=True,secure=secure_cookie,samesite='strict',max_age=8*3600)
        return resp
    @app.get('/api/blueprint/session')
    def session(user=Depends(authorize)):return {'csrf':user['csrf'],'role':user['role']}
    @app.post('/api/blueprint/logout')
    def logout(request:Request,user=Depends(authorize)):
        sessions.pop(request.cookies.get('bp_session'),None)
        resp=JSONResponse({'ok':True});resp.delete_cookie('bp_session');return resp
    install(app,store,authorize,github)
    return app

def main():
    p=argparse.ArgumentParser();p.add_argument('--db',default='blueprint.sqlite');p.add_argument('--users',default='blueprint-users.json');p.add_argument('--init-owner',action='store_true');p.add_argument('--port',type=int,default=8765);p.add_argument('--local-http',action='store_true')
    a=p.parse_args()
    if a.init_owner:
        pwd=getpass.getpass('Пароль директора (не менее 12 символов): ')
        if len(pwd)<12:raise SystemExit('Пароль слишком короткий')
        fd=os.open(a.users,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:json.dump({'owner':{'hash':password_hash(pwd),'role':'owner'}},f)
        return
    users=json.loads(Path(a.users).read_text())
    import uvicorn
    uvicorn.run(create_app(a.db,users,not a.local_http),host='127.0.0.1',port=a.port)

if __name__=='__main__':main()
