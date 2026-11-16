import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from backend.blueprint.engine import *
from backend.blueprint.store import Store,Conflict
from backend.blueprint.app import create_app,password_hash

ROOT=Path(__file__).resolve().parents[2]
def example():return json.loads((ROOT/'examples/blueprint/sea-coop.json').read_text())
def raw(p):return json.dumps(p,ensure_ascii=False).encode()
def independent():
    p=example();p['tasks'][0]['file_scopes']=['authority/**'];p['tasks'][1]['file_scopes']=['client/**'];return p

class ContractTests(unittest.TestCase):
    def setUp(self):self.p=example()
    def test_three_engines_and_structures(self):
        for f in (ROOT/'examples/blueprint').glob('*.json'):
            p=parse(f.read_bytes());self.assertTrue(schedule(p,{})['ready'])
    def test_reference(self):self.assertEqual(validate(parse((ROOT/'project_blueprint.example.json').read_bytes())),[])
    def test_version(self):self.p['schema_version']='2.0';self.assertTrue(validate(self.p))
    def test_missing_field(self):del self.p['project']['engine'];self.assertTrue(validate(self.p))
    def test_wrong_priority(self):self.p['tasks'][0]['priority']='100';self.assertTrue(validate(self.p))
    def test_empty_acceptance(self):self.p['tasks'][0]['acceptance']=[];self.assertTrue(validate(self.p))
    def test_metadata(self):self.p['metadata']={'note':'anything','command':'echo never-run'};self.assertFalse(validate(self.p))
    def test_state_not_contract(self):self.p['tasks'][0]['status']='accepted';self.assertEqual(schedule(self.p,{})['blocked']['A3'],['Ожидает принятия: A1, A2'])
    def test_duplicate_ids(self):self.p['tasks'][1]['id']='A1';self.assertTrue(validate(self.p))
    def test_duplicate_stage(self):self.p['stages'][1]['id']='M1';self.assertTrue(validate(self.p))
    def test_unassigned_task(self):self.p['stages'][1]['tasks']=['A2'];self.assertTrue(validate(self.p))
    def test_missing_dependency(self):self.p['tasks'][0]['dependencies']=['missing'];self.assertTrue(validate(self.p))
    def test_self_cycle(self):self.p['tasks'][0]['dependencies']=['A1'];self.assertTrue(validate(self.p))
    def test_cycle(self):self.p['tasks'][0]['dependencies']=['A3'];self.assertTrue(validate(self.p))
    def test_traversal(self):self.p['tasks'][0]['file_scopes']=['a/../b'];self.assertTrue(validate(self.p))
    def test_absolute(self):self.p['documents']['gdd']=['/etc/passwd'];self.assertTrue(validate(self.p))
    def test_encoded_traversal(self):self.p['documents']['roadmap']=['docs/%2e%2e/x'];self.assertTrue(validate(self.p))
    def test_windows_path(self):self.p['tasks'][0]['file_scopes']=['C:\\x'];self.assertTrue(validate(self.p))
    def test_branch_injection(self):self.p['tasks'][0]['branch']='feat/$(whoami)';self.assertTrue(validate(self.p))
    def test_main_branch(self):self.p['tasks'][0]['branch']='main';self.assertTrue(validate(self.p))
    def test_empty_zones_valid(self):self.assertFalse(validate(self.p))
    def test_oversize(self):
        with self.assertRaises(ValueError):parse(b' '* (MAX_BYTES+1))
    def test_duplicate_json_key(self):
        with self.assertRaises(ValueError):parse(b'{"x":1,"x":2}')
    def test_invalid_json(self):
        with self.assertRaises(ValueError):parse(b'{')
    def test_scalar(self):
        with self.assertRaises(ValueError):parse(b'[]')
    def test_nonfinite(self):
        with self.assertRaises(ValueError):parse(b'{"x":NaN}')

class SchedulerTests(unittest.TestCase):
    def setUp(self):self.p=independent()
    def test_priority(self):self.assertEqual(schedule(self.p,{})['ready'],['A1','A2'])
    def test_tie_deterministic(self):self.p['tasks'][1]['priority']=100;self.p['tasks'].reverse();self.assertEqual(schedule(self.p,{})['ready'],['A1','A2'])
    def test_parallel_disjoint(self):self.assertEqual(schedule(self.p,{})['parallel_batches'],[['A1','A2']])
    def test_unknown_serial(self):self.p['tasks'][0]['file_scopes']=[];self.assertEqual(schedule(self.p,{})['parallel_batches'],[['A1'],['A2']])
    def test_unknown_active_blocks(self):self.p['tasks'][0]['file_scopes']=[];self.assertFalse(schedule(self.p,{'A1':{'status':'in_progress'}})['ready'])
    def test_confirmed_override(self):self.p['tasks'][0]['file_scopes']=[];self.assertEqual(schedule(self.p,{'A1':{'scopes':['authority/**']}})['parallel_batches'],[['A1','A2']])
    def test_wildcards(self):self.assertTrue(overlap(['src/*/one'],['src/two/**']))
    def test_parent(self):self.assertTrue(overlap(['src'],['src/deep/file']))
    def test_root_glob(self):self.assertTrue(overlap(['**/*.py'],['client/a.ts']))
    def test_same_file(self):self.assertTrue(overlap(['a.txt'],['a.txt']))
    def test_sibling(self):self.assertFalse(overlap(['src/a/**'],['src/b/**']))
    def test_unaccepted_ci(self):self.assertIn('A3',schedule(self.p,{'A1':{'status':'tests_passed'},'A2':{'status':'accepted'}})['blocked'])
    def test_accepted_unlocks(self):self.assertEqual(schedule(self.p,{'A1':{'status':'accepted'},'A2':{'status':'accepted'}})['ready'],['A3'])
    def test_cancelled_blocks(self):self.assertIn('A3',schedule(self.p,{'A1':{'status':'cancelled'}})['blocked'])
    def test_active_conflicts(self):self.p['tasks'][1]['file_scopes']=['authority/x'];self.assertIn('A2',schedule(self.p,{'A1':{'status':'in_progress'}})['blocked'])
    def test_same_branch_serial(self):self.p['tasks'][1]['branch']=self.p['tasks'][0]['branch'];self.assertEqual(schedule(self.p,{})['parallel_batches'],[['A1'],['A2']])
    def test_prompt_preserved(self):self.assertTrue(render_prompt(self.p,self.p['tasks'][0],{'A1':{'reviewed':True}}).endswith(self.p['tasks'][0]['prompt']))
    def test_prompt_unreviewed(self):
        with self.assertRaises(ValueError):render_prompt(self.p,self.p['tasks'][0],{})
    def test_prompt_blocked(self):
        with self.assertRaises(ValueError):render_prompt(self.p,self.p['tasks'][2],{'A3':{'reviewed':True}})
    def test_prompt_conflict(self):self.p['tasks'][0]['prompt']='Выполни автоматическое слияние PR';self.assertTrue(prompt_conflicts(self.p['tasks'][0]))
    def test_prompt_no_invented_sha(self):self.p['project']['base_sha']='a'*40;self.assertIn('не получен',render_prompt(self.p,self.p['tasks'][0],{'A1':{'reviewed':True}}))
    def test_context(self):s=render_prompt(self.p,self.p['tasks'][0],{'A1':{'reviewed':True}});self.assertIn('Критерии приёмки',s);self.assertIn('Формат отчёта',s)

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.sqlite';self.s=Store(self.path);self.p=independent();self.v=self.s.import_plan(raw(self.p),'owner');self.s.approve(self.v,'owner',None)
    def tearDown(self):self.tmp.cleanup()
    def review(self,tid='A1'):self.s.review('sea-coop',tid,'owner',self.v,'Смысл и ограничения проверены')
    def move(self,status,tid='A1',role='owner',note='Решение директора'):
        old=self.s.snapshot('sea-coop')['states'][tid]['status'];self.s.transition('sea-coop',tid,status,'user',role,self.v,old,note)
    def accept(self,tid='A1'):self.review(tid);self.move('in_progress',tid);self.move('tests_passed',tid);self.move('accepted',tid)
    def test_migrate_idempotent(self):Store(self.path);self.assertEqual(self.s.snapshot('sea-coop')['version'],self.v)
    def test_migration_preserves_unrelated(self):
        with self.s.connection() as db:db.execute('CREATE TABLE unrelated(x)');db.execute('INSERT INTO unrelated VALUES(1)');db.commit()
        Store(self.path)
        with self.s.connection() as db:self.assertEqual(db.execute('SELECT x FROM unrelated').fetchone()[0],1)
    def test_unknown_migration(self):
        with self.s.connection() as db:db.execute('INSERT INTO bp_migrations VALUES(999)');db.commit()
        with self.assertRaises(ValueError):Store(self.path)
    def test_immutable(self):
        with self.s.connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE bp_versions SET document='{}'")
    def test_no_history_delete(self):
        with self.s.connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM bp_events')
    def test_no_version_delete(self):
        with self.s.connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM bp_versions')
    def test_status_does_not_mutate_plan(self):before=self.s.snapshot('sea-coop')['hash'];self.accept();self.assertEqual(self.s.snapshot('sea-coop')['hash'],before)
    def test_tests_do_not_accept(self):self.review();self.move('in_progress');self.move('tests_passed');self.assertIn('A3',self.s.snapshot('sea-coop')['queue']['blocked'])
    def test_executor_cannot_accept(self):
        self.review();self.move('in_progress');self.move('tests_passed')
        with self.assertRaises(PermissionError):self.move('accepted',role='executor')
    def test_accept_requires_reason(self):
        self.review();self.move('in_progress');self.move('tests_passed')
        with self.assertRaises(ValueError):self.move('accepted',note='')
    def test_illegal_transition(self):
        with self.assertRaises(Conflict):self.move('accepted')
    def test_dispatch_requires_review(self):
        with self.assertRaises(ValueError):self.move('in_progress')
    def test_scope_edit_active_denied(self):
        self.review();self.move('in_progress')
        with self.assertRaises(Conflict):self.review()
    def test_scope_review_traversal(self):
        with self.assertRaises(ValueError):self.s.review('sea-coop','A1','owner',self.v,'ok',['../secret'])
    def test_stale_version(self):
        with self.assertRaises(Conflict):self.s.transition('sea-coop','A1','ready','user','owner',999,'todo')
    def test_stale_status(self):
        with self.assertRaises(Conflict):self.s.transition('sea-coop','A1','ready','user','owner',self.v,'ready')
    def test_import_not_approve(self):self.p['tasks'][0]['title']='New';v=self.s.import_plan(raw(self.p),'owner');self.assertNotEqual(self.s.snapshot('sea-coop')['version'],v)
    def test_diff_dependencies(self):
        self.p['tasks'][1]['dependencies']=['A1'];v=self.s.import_plan(raw(self.p),'owner')
        with self.s.connection() as db:self.assertEqual(self.s.preview(db,v)['diff']['dependencies_changed'],['A2'])
    def test_changed_accepted_requires_reset(self):
        self.accept();self.p['tasks'][0]['title']='New';v=self.s.import_plan(raw(self.p),'owner')
        with self.assertRaises(Conflict):self.s.approve(v,'owner',self.v)
        self.s.approve(v,'owner',self.v,['A1']);self.assertEqual(self.s.snapshot('sea-coop')['states']['A1']['status'],'todo')
    def test_unchanged_status_preserved(self):self.accept();self.p['tasks'][1]['title']='new';v=self.s.import_plan(raw(self.p),'owner');self.s.approve(v,'owner',self.v);self.assertEqual(self.s.snapshot('sea-coop')['states']['A1']['status'],'accepted')
    def test_active_update_ack(self):
        self.review();self.move('in_progress');self.p['tasks'][0]['title']='new';v=self.s.import_plan(raw(self.p),'owner')
        with self.assertRaises(Conflict):self.s.approve(v,'owner',self.v)
        self.s.approve(v,'owner',self.v,ack_active=True)
    def test_retired_history_preserved(self):
        self.accept();self.p['tasks']=self.p['tasks'][1:];self.p['tasks'][1]['dependencies']=['A2'];self.p['stages'][0]['tasks']=['A2'];v=self.s.import_plan(raw(self.p),'owner');self.s.approve(v,'owner',self.v);self.assertTrue(any(e['task']=='A1' for e in self.s.history('sea-coop')))
    def test_atomic_competing_dispatch(self):
        self.p['tasks'][0]['file_scopes']=[];v=self.s.import_plan(raw(self.p),'owner');self.s.approve(v,'owner',self.v);self.v=v;self.review('A1');self.review('A2')
        def start(t):
            try:self.s.transition('sea-coop',t,'in_progress','owner','owner',v,'todo');return True
            except (Conflict,ValueError):return False
        with ThreadPoolExecutor(2) as pool:self.assertEqual(sum(pool.map(start,['A1','A2'])),1)
    def test_evidence_history_survives_update(self):
        self.review();self.move('in_progress');self.s.transition('sea-coop','A1','pr_open','owner','owner',self.v,'in_progress',pr=7,evidence={'unit':'pass'});self.p['tasks'][1]['title']='changed';v=self.s.import_plan(raw(self.p),'owner');self.s.approve(v,'owner',self.v);self.assertEqual(self.s.snapshot('sea-coop')['states']['A1']['pr'],7)
    def test_removed_active_blocked(self):
        self.review('A2');self.move('in_progress','A2');self.p['tasks'].pop(1);self.p['tasks'][1]['dependencies']=['A1'];self.p['stages'][0]['tasks']=['A1'];v=self.s.import_plan(raw(self.p),'owner')
        with self.assertRaises(Conflict):self.s.approve(v,'owner',self.v,ack_active=True)
    def test_audit_records_actor(self):self.review();self.assertEqual(self.s.history('sea-coop')[-1]['actor'],'owner')

class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.users={r:{'hash':password_hash('test-password-only'),'role':r} for r in ['owner','executor','viewer']}
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.app=create_app(Path(self.tmp.name)/'api.sqlite',self.users,False);self.c=TestClient(self.app)
    def tearDown(self):self.c.close();self.tmp.cleanup()
    def login(self,role='owner'):
        r=self.c.post('/api/blueprint/login',json={'username':role,'password':'test-password-only'});self.assertEqual(r.status_code,200);self.c.headers['X-CSRF-Token']=r.json()['csrf']
    def test_anonymous_read_denied(self):self.assertEqual(self.c.get('/api/blueprint/versions').status_code,401)
    def test_bad_password(self):self.assertEqual(self.c.post('/api/blueprint/login',json={'username':'owner','password':'bad'}).status_code,401)
    def test_rate_limit(self):
        for _ in range(8):self.c.post('/api/blueprint/login',json={})
        self.assertEqual(self.c.post('/api/blueprint/login',json={}).status_code,429)
    def test_csrf_required(self):self.login();del self.c.headers['X-CSRF-Token'];self.assertEqual(self.c.post('/api/blueprint/import',content=raw(example())).status_code,403)
    def test_executor_cannot_import(self):self.login('executor');self.assertEqual(self.c.post('/api/blueprint/import',content=raw(example())).status_code,403)
    def test_viewer_cannot_import(self):self.login('viewer');self.assertEqual(self.c.post('/api/blueprint/import',content=raw(example())).status_code,403)
    def test_bad_schema(self):self.login();self.assertEqual(self.c.post('/api/blueprint/import',json={}).status_code,400)
    def test_size_stream_limit(self):self.login();self.assertEqual(self.c.post('/api/blueprint/import',content=b'a'*(MAX_BYTES+1)).status_code,413)
    def test_import_approve_queue(self):
        self.login();v=self.c.post('/api/blueprint/import',content=raw(example())).json()['version'];self.assertEqual(self.c.post(f'/api/blueprint/versions/{v}/approve',json={'expected_version':None}).status_code,200);self.assertTrue(self.c.get('/api/blueprint/projects/sea-coop').json()['queue']['ready'])
    def test_viewer_cannot_approve(self):
        self.login();v=self.c.post('/api/blueprint/import',content=raw(example())).json()['version'];self.login('viewer');self.assertEqual(self.c.post(f'/api/blueprint/versions/{v}/approve',json={'expected_version':None}).status_code,403)
    def test_logout_revokes(self):self.login();self.c.post('/api/blueprint/logout');self.assertEqual(self.c.get('/api/blueprint/session').status_code,401)
    def test_csp(self):self.assertIn("script-src 'self'",self.c.get('/blueprint').headers['Content-Security-Policy'])
    def test_cookie(self):r=self.c.post('/api/blueprint/login',json={'username':'owner','password':'test-password-only'});self.assertIn('HttpOnly',r.headers['set-cookie']);self.assertIn('SameSite=strict',r.headers['set-cookie'])
    def test_static_escape(self):self.assertNotEqual(self.c.get('/blueprint/assets/../store.py').status_code,200)
    def test_no_html_injection_sink(self):self.assertNotIn('innerHTML',(ROOT/'backend/blueprint/static/app.js').read_text())
    def test_missing_github_fallback(self):self.login();self.assertEqual(self.c.post('/api/blueprint/projects/sea-coop/tasks/A1/github',json={'version':1}).status_code,503)


class DispatchTests(unittest.TestCase):
    setUp=StoreTests.setUp
    tearDown=StoreTests.tearDown
    review=StoreTests.review
    move=StoreTests.move
    accept=StoreTests.accept
    # Separate dispatch scenarios exercise atomic reservation rather than read-only preview.
    def test_dispatch_reserves(self):self.review();text=self.s.dispatch('sea-coop','A1','owner',self.v);self.assertTrue(text.endswith(self.p['tasks'][0]['prompt']));self.assertEqual(self.s.snapshot('sea-coop')['states']['A1']['status'],'in_progress')
    def test_dispatch_replay(self):self.review();text=self.s.dispatch('sea-coop','A1','owner',self.v);self.assertEqual(self.s.dispatch('sea-coop','A1','owner',self.v),text)
    def test_dispatch_cannot_skip_dependencies(self):
        self.review('A3')
        with self.assertRaises(ValueError):self.s.dispatch('sea-coop','A3','owner',self.v)
    def test_depth(self):
        with self.assertRaises(ValueError):parse(b'['*40+b'0'+b']'*40)
    def test_reimport_after_stale_parent(self):
        a=copy.deepcopy(self.p);a['tasks'][0]['title']='Draft A';v1=self.s.import_plan(raw(a),'owner')
        b=copy.deepcopy(self.p);b['tasks'][0]['title']='Draft B';v2=self.s.import_plan(raw(b),'owner');self.s.approve(v2,'owner',self.v)
        with self.assertRaises(Conflict):self.s.approve(v1,'owner',v2)
        fresh=self.s.import_plan(raw(a),'owner');self.assertNotEqual(fresh,v1);self.s.approve(fresh,'owner',v2)
    def test_removed_reintroduced_accepted_requires_reset(self):
        self.accept('A2');removed=copy.deepcopy(self.p);removed['tasks'].pop(1);removed['tasks'][1]['dependencies']=['A1'];removed['stages'][0]['tasks']=['A1'];v=self.s.import_plan(raw(removed),'owner');self.s.approve(v,'owner',self.v)
        new=self.s.import_plan(raw(self.p),'owner')
        with self.assertRaises(Conflict):self.s.approve(new,'owner',v)
        self.s.approve(new,'owner',v,['A2'])
    def test_transitive_acceptance_reset(self):
        self.accept('A1');self.accept('A2');self.accept('A3');self.p['tasks'][0]['title']='new';v=self.s.import_plan(raw(self.p),'owner')
        with self.s.connection() as db:self.assertEqual(self.s.preview(db,v)['reset_required'],['A1','A3'])
    def test_context_change_reset(self):
        self.accept('A1');self.p['documents']['gdd']=['docs/New.md'];v=self.s.import_plan(raw(self.p),'owner')
        with self.s.connection() as db:self.assertEqual(self.s.preview(db,v)['reset_required'],['A1'])

class FakeGitHub:
    def __init__(self):self.mutated=False;self.calls=0
    def get_pr(self,repo,n):
        self.calls+=1
        return {'head':{'ref':'feature/sea-coop-a1','sha':('b' if self.mutated and self.calls>1 else 'a')*40,'repo':{'full_name':repo}},'base':{'ref':'main','repo':{'full_name':repo}},'state':'closed','merged':True}
    def check_runs(self,repo,sha):return [{'name':'unit','conclusion':'success','head_sha':sha}]
    def combined_status(self,repo,sha):return [{'context':'lint','state':'success'}]
    def pr_files(self,repo,n):return [{'filename':'authority/api.py','status':'modified'}]

class GitHubTests(unittest.TestCase):
    setUp=StoreTests.setUp
    tearDown=StoreTests.tearDown
    review=StoreTests.review
    move=StoreTests.move
    accept=StoreTests.accept
    def attach(self):self.review();self.move('in_progress');self.s.transition('sea-coop','A1','pr_open','owner','owner',self.v,'in_progress',pr=2)
    def test_github_no_auto_accept(self):self.attach();r=self.s.github_sync('sea-coop','A1','owner',self.v,FakeGitHub());self.assertTrue(r['merged']);self.assertEqual(self.s.snapshot('sea-coop')['states']['A1']['status'],'pr_open')
    def test_github_files_sha(self):self.attach();r=self.s.github_sync('sea-coop','A1','owner',self.v,FakeGitHub());self.assertEqual(r['sha'],'a'*40);self.assertEqual(r['files'][0]['filename'],'authority/api.py')
    def test_github_sha_race(self):
        self.attach();g=FakeGitHub();g.mutated=True
        with self.assertRaises(Conflict):self.s.github_sync('sea-coop','A1','owner',self.v,g)
    def test_github_history(self):self.attach();self.s.github_sync('sea-coop','A1','owner',self.v,FakeGitHub());self.assertEqual(self.s.history('sea-coop')[-1]['action'],'github')
    def test_github_needs_pr(self):
        with self.assertRaises(ValueError):self.s.github_sync('sea-coop','A1','owner',self.v,FakeGitHub())

if __name__=='__main__':unittest.main()
