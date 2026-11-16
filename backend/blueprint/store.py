"""Transactional SQLite storage. No connection to existing production databases."""
from __future__ import annotations
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from .engine import (ACTIVE,TRANSITIONS,canonical,digest,diff,parse,safe_path,
                     schedule,render_prompt,prompt_conflicts)

class Conflict(ValueError):pass

class Store:
    def __init__(self,path):
        self.path=str(path)
        # No destructive migration; fail rather than silently downgrade unknown schema.
        with self.connection() as db:
            exists=db.execute("SELECT name FROM sqlite_master WHERE name='bp_migrations'").fetchone()
            if exists and db.execute('SELECT max(version) FROM bp_migrations').fetchone()[0]>1:
                raise ValueError('Версия БД новее приложения')
            db.executescript('BEGIN IMMEDIATE;\n'+(Path(__file__).parent/'migrations/001_blueprint.sql').read_text()+'\nCOMMIT;')
    @contextmanager
    def connection(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        try:yield db
        finally:db.close()
    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:yield db;db.commit()
            except Exception:db.rollback();raise
    def event(self,db,project,actor,action,detail,task=None,version=None):
        db.execute('INSERT INTO bp_events(project,task,version,actor,action,detail) VALUES(?,?,?,?,?,?)',
                   (project,task,version,actor,action,canonical(detail)))
    def current(self,db,project):
        row=db.execute('SELECT v.* FROM bp_projects p JOIN bp_versions v ON v.id=p.current_version WHERE p.project=?',(project,)).fetchone()
        return dict(row) if row else None
    def states(self,db,project):
        result={}
        for r in db.execute('SELECT * FROM bp_tasks WHERE project=?',(project,)):
            d=dict(r)
            if d['scopes'] is None:d.pop('scopes')
            else:d['scopes']=json.loads(d['scopes'])
            d['evidence']=json.loads(d['evidence']);result[d['task']]=d
        return result
    def import_plan(self,raw,actor):
        plan=parse(raw);project=plan['project']['id'];h=digest(plan)
        with self.transaction() as db:
            cur=self.current(db,project)
            parent=cur['id'] if cur else None
            row=db.execute('SELECT id FROM bp_versions WHERE project=? AND hash=? AND (parent_id IS ? OR id IS ?)',(project,h,parent,parent)).fetchone()
            if row:return row[0]
            version=db.execute('INSERT INTO bp_versions(project,document,hash,imported_by,parent_id) VALUES(?,?,?,?,?)',
                               (project,canonical(plan),h,actor,cur['id'] if cur else None)).lastrowid
            self.event(db,project,actor,'import',{'hash':h},version=version)
            return version
    def preview(self,db,version):
        row=db.execute('SELECT * FROM bp_versions WHERE id=?',(version,)).fetchone()
        if not row:raise ValueError('Версия не найдена')
        row=dict(row);new=json.loads(row['document']);cur=self.current(db,row['project'])
        baseline=cur
        if row['approved_at']:
            parent=db.execute('SELECT * FROM bp_versions WHERE id=?',(row['parent_id'],)).fetchone()
            baseline=dict(parent) if parent else None
        old=json.loads(baseline['document']) if baseline else None
        delta=diff(old,new);states=self.states(db,row['project'])
        affected=set(delta['changed']+delta['removed']) | (set(delta['added']) & set(states))
        if delta['context_changed']:affected.update(states)
        # Invalidate accepted descendants as well when their prerequisites change.
        while True:
            more={t['id'] for t in new['tasks'] if set(t['dependencies'])&affected}
            if more<=affected:break
            affected|=more
        active=sorted(k for k in affected if states.get(k,{}).get('status') in ACTIVE)
        reset=sorted(k for k in affected if states.get(k,{}).get('status')=='accepted' and k in {t['id'] for t in new['tasks']})
        before={t['id']:t for t in old['tasks']} if old else {}
        after={t['id']:t for t in new['tasks']}
        changes={k:{field:{'before':before[k].get(field),'after':after[k].get(field)} for field in before[k].keys()|after[k].keys() if before[k].get(field)!=after[k].get(field)} for k in delta['changed']}
        return {**row,'plan':new,'diff':delta,'task_changes':changes,'compared_to_version':baseline['id'] if baseline else None,'active_affected':active if not row['approved_at'] else [],'reset_required':reset if not row['approved_at'] else [],
                'current_version':cur['id'] if cur else None,'affected':sorted(affected)}
    def approve(self,version,actor,expected_version,reset_ids=(),ack_active=False):
        with self.transaction() as db:
            p=self.preview(db,version);project=p['project'];cur=self.current(db,project)
            if p['approved_at']:raise Conflict('Версия уже утверждена')
            if expected_version!=p['current_version'] or p['parent_id']!=p['current_version']:
                raise Conflict('План изменился после импорта; импортируйте новую версию заново с актуальным контекстом')
            if set(reset_ids)!=set(p['reset_required']):raise Conflict('Требуется явное подтверждение сброса: '+', '.join(p['reset_required']))
            if p['active_affected'] and not ack_active:raise Conflict('Изменены активные задачи; требуется подтверждение')
            states=self.states(db,project)
            if any(k in p['diff']['removed'] for k in p['active_affected']):raise Conflict('Перед удалением активной задачи отмените её')
            db.execute('UPDATE bp_versions SET approved_by=?,approved_at=CURRENT_TIMESTAMP WHERE id=?',(actor,version))
            db.execute('INSERT INTO bp_projects(project,current_version) VALUES(?,?) ON CONFLICT(project) DO UPDATE SET current_version=excluded.current_version',(project,version))
            for t in p['plan']['tasks']:
                tid=t['id']
                db.execute('INSERT OR IGNORE INTO bp_tasks(project,task) VALUES(?,?)',(project,tid))
                if tid in p['affected'] or (tid in p['diff']['added'] and tid in states):
                    # Added IDs may be retired/reintroduced: never resurrect old acceptance.
                    db.execute("UPDATE bp_tasks SET status='todo',scopes=NULL,reviewed=0,review_note='',executor='' WHERE project=? AND task=?",(project,tid))
            self.event(db,project,actor,'approve',{'diff':p['diff'],'reset':list(reset_ids),'active_ack':ack_active},version=version)
    def snapshot(self,project):
        with self.connection() as db:
            cur=self.current(db,project)
            if not cur:raise ValueError('Нет утверждённого Blueprint')
            plan=json.loads(cur['document']);states=self.states(db,project)
            return {'version':cur['id'],'hash':cur['hash'],'plan':plan,'states':states,'queue':schedule(plan,states)}
    def versions(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute('SELECT id,project,hash,imported_at,approved_at,approved_by FROM bp_versions ORDER BY id DESC')]
    def history(self,project):
        with self.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM bp_events WHERE project=? ORDER BY id',(project,))]
    def _context(self,db,project,tid,expected_version):
        cur=self.current(db,project)
        if not cur or cur['id']!=expected_version:raise Conflict('Версия устарела, обновите экран')
        plan=json.loads(cur['document']);task=next((t for t in plan['tasks'] if t['id']==tid),None)
        if task is None:raise ValueError('Задача не входит в текущий план')
        return plan,task,self.states(db,project)
    def review(self,project,tid,actor,version,note,scopes=None):
        if not isinstance(note,str) or not note.strip() or len(note)>4000:raise ValueError('Нужен результат проверки ограничений')
        if scopes is not None and (not isinstance(scopes,list) or len(scopes)>500 or any(not safe_path(x) for x in scopes)):
            raise ValueError('Небезопасные файловые зоны')
        with self.transaction() as db:
            plan,task,states=self._context(db,project,tid,version)
            active=states[tid]['status'] in ACTIVE
            if states[tid]['status']=='accepted' or (active and (states[tid].get('scopes',task['file_scopes']) or not scopes)):
                raise Conflict('Нельзя менять подтверждённые зоны выданной задачи')
            if active:
                hypothetical={**states,tid:{**states[tid],'status':'todo','scopes':scopes}}
                if tid not in schedule(plan,hypothetical)['ready']:raise Conflict('Уточнение создаёт конфликт с активной работой')
            if prompt_conflicts(task):raise Conflict('; '.join(prompt_conflicts(task)))
            db.execute('UPDATE bp_tasks SET reviewed=1,review_note=?,scopes=? WHERE project=? AND task=?',
                       (note,canonical(scopes) if scopes is not None else None,project,tid))
            self.event(db,project,actor,'review',{'note':note,'scopes':scopes},tid,version)
            if active:
                updated=self.states(db,project)
                text=render_prompt(plan,task,updated,allow_active=True)
                db.execute('INSERT INTO bp_dispatches(project,task,version,actor,prompt) VALUES(?,?,?,?,?)',(project,tid,version,actor,text))
                self.event(db,project,actor,'scope_clarification',{'scopes':scopes,'prompt_hash':digest(text)},tid,version)
    def prompt(self,project,tid,version,base_sha=None):
        with self.connection() as db:
            plan,task,states=self._context(db,project,tid,version)
            # SHA is only trusted from a fresh GitHub branch read, never from imported metadata.
            return render_prompt(plan,task,states,base_sha)
    def dispatch(self,project,tid,actor,version,base_sha=None):
        with self.transaction() as db:
            plan,task,states=self._context(db,project,tid,version)
            if states[tid]['status'] in ACTIVE:
                old=db.execute('SELECT prompt FROM bp_dispatches WHERE project=? AND task=? ORDER BY id DESC LIMIT 1',(project,tid)).fetchone()
                if old:return old['prompt']
                raise Conflict('Задача выдана вручную; снимок промпта отсутствует')
            prompt=render_prompt(plan,task,states,base_sha)
            if any(t['branch']==task['branch'] and states[t['id']]['status'] in ACTIVE for t in plan['tasks'] if t['id']!=tid):
                raise Conflict('Рабочая ветка занята')
            db.execute("UPDATE bp_tasks SET status='in_progress',executor=? WHERE project=? AND task=?",(actor,project,tid))
            db.execute('INSERT INTO bp_dispatches(project,task,version,actor,prompt) VALUES(?,?,?,?,?)',(project,tid,version,actor,prompt))
            self.event(db,project,actor,'dispatch',{'from':states[tid]['status'],'to':'in_progress','prompt_hash':digest(prompt)},tid,version)
            return prompt
    def transition(self,project,tid,status,actor,role,version,expected_status,note='',executor='',pr=None,evidence=None):
        if not isinstance(status,str) or not isinstance(expected_status,str):raise ValueError('Статус должен быть строкой')
        if not isinstance(note,str) or len(note)>20000 or not isinstance(executor,str) or len(executor)>200:raise ValueError('Некорректный отчёт или исполнитель')
        with self.transaction() as db:
            plan,task,states=self._context(db,project,tid,version);old=states[tid]['status']
            if old!=expected_status:raise Conflict('Статус изменился, обновите экран')
            if status not in TRANSITIONS[old]:raise Conflict('Недопустимый переход статуса')
            if status=='accepted':
                if role!='owner':raise PermissionError('Только директор принимает задачу')
                if not isinstance(note,str) or not note.strip():raise ValueError('Нужно решение о приёмке')
                if any(states[d]['status']!='accepted' for d in task['dependencies']):raise Conflict('Зависимости не приняты')
            if status in ('ready','in_progress') and old in ('todo','ready'):
                if tid not in schedule(plan,states)['ready']:raise Conflict('Задача заблокирована')
                if status=='in_progress':
                    issued=render_prompt(plan,task,states)
                    if any(t['branch']==task['branch'] and states[t['id']]['status'] in ACTIVE for t in plan['tasks'] if t['id']!=tid):
                        raise Conflict('Рабочая ветка занята')
                    db.execute('INSERT INTO bp_dispatches(project,task,version,actor,prompt) VALUES(?,?,?,?,?)',(project,tid,version,actor,issued))
            # Resuming blocked/failed work requires fresh scheduling and prompt review.
            if status=='todo':db.execute('UPDATE bp_tasks SET reviewed=0 WHERE project=? AND task=?',(project,tid))
            if pr is not None and (type(pr)!=int or pr<1):raise ValueError('Некорректный номер PR')
            if evidence is not None and (not isinstance(evidence,dict) or len(canonical(evidence))>64000):raise ValueError('Некорректные результаты тестов')
            db.execute('UPDATE bp_tasks SET status=?,executor=?,pr=COALESCE(?,pr),evidence=COALESCE(?,evidence) WHERE project=? AND task=?',
                       (status,executor or states[tid]['executor'],pr,canonical(evidence) if evidence is not None else None,project,tid))
            self.event(db,project,actor,'status',{'from':old,'to':status,'note':note,'pr':pr,'evidence':evidence},tid,version)
    def github_sync(self,project,tid,actor,version,client):
        # Existing portal GitHubClient is injected. GETs only, never merges or executes.
        snap=self.snapshot(project)
        if snap['version']!=version:raise Conflict('Версия устарела')
        task=next(t for t in snap['plan']['tasks'] if t['id']==tid);number=snap['states'][tid]['pr']
        if not number:raise ValueError('Сначала привяжите PR')
        repo=snap['plan']['project']['repository'];pr=client.get_pr(repo,number)
        if pr['head']['ref']!=task['branch'] or pr['base']['ref']!=snap['plan']['project']['base_branch']:
            raise Conflict('PR относится к другой ветке')
        if pr['head'].get('repo',{}).get('full_name')!=repo or pr['base'].get('repo',{}).get('full_name')!=repo:
            raise Conflict('PR относится к другому репозиторию или форку')
        sha=pr['head']['sha'];checks=client.check_runs(repo,sha);statuses=client.combined_status(repo,sha)
        files=client.pr_files(repo,number) if hasattr(client,'pr_files') else []
        fresh=client.get_pr(repo,number)
        if fresh['head']['sha']!=sha:raise Conflict('SHA изменился при проверке')
        evidence={'source':'github','pr':number,'sha':sha,'state':pr['state'],'merged':bool(pr.get('merged')),
                  'checks':checks,'statuses':statuses,'files':files,'files_available':hasattr(client,'pr_files')}
        with self.transaction() as db:
            _,_,states=self._context(db,project,tid,version)
            if states[tid]['pr']!=number:raise Conflict('PR был изменён')
            db.execute('UPDATE bp_tasks SET evidence=? WHERE project=? AND task=?',(canonical(evidence),project,tid))
            self.event(db,project,actor,'github',evidence,tid,version)
        return evidence
