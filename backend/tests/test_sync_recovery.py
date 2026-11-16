"""Reconciliation of historical merged PRs after portal project registration."""
from backend.github import sync
from backend.roadmap import service as roadmap
from .conftest import make_project


def _import(portal, project):
    roadmap.import_plan(portal.db, project, {"project":"Game","stages":[],"tasks":[
        {"id":"T0","title":"GDD","branch":"task/t0","status":"planned","depends_on":[]},
        {"id":"T1","title":"Catalog","branch":"task/t1","status":"planned","depends_on":["T0"]},
    ]})


def test_recovers_merged_pr_with_different_branch(portal, fake_gh):
    fake_gh.add_repo("owner/game")
    project=make_project(portal, auto_merge_enabled=0)
    _import(portal, project)
    pr=fake_gh.add_pr("owner/game",2,"task/t0-gdd-bizmania","a"*40,"[T0] GDD")
    pr.update(state="closed",merged=True,merge_commit_sha="b"*40)
    result=sync.sync_project(portal,project)
    assert result["merged_recovered"]==1
    assert roadmap.get_task(portal.db,project["id"],"T0")["status"]=="done"
    assert roadmap.get_task(portal.db,project["id"],"T1")["status"]=="ready"
    assert sync.sync_project(portal,project)["merged_recovered"]==0


def test_closed_unmerged_not_done(portal, fake_gh):
    fake_gh.add_repo("owner/game")
    project=make_project(portal, auto_merge_enabled=0)
    _import(portal,project)
    pr=fake_gh.add_pr("owner/game",2,"task/t0","a"*40,"[T0] GDD")
    pr.update(state="closed",merged=False)
    sync.sync_project(portal,project)
    assert roadmap.get_task(portal.db,project["id"],"T0")["status"]!="done"


def test_open_pr_detected_after_recovery(portal, fake_gh):
    fake_gh.add_repo("owner/game")
    project=make_project(portal, auto_merge_enabled=0)
    _import(portal,project)
    old=fake_gh.add_pr("owner/game",2,"task/t0-gdd","a"*40,"[T0] GDD")
    old.update(state="closed",merged=True,merge_commit_sha="b"*40)
    fake_gh.add_pr("owner/game",4,"task/t1","c"*40,"[T1] Catalog")
    sync.sync_project(portal,project)
    assert roadmap.get_task(portal.db,project["id"],"T0")["status"]=="done"
    assert roadmap.get_task(portal.db,project["id"],"T1")["status"]=="in_progress"
    assert roadmap.get_task(portal.db,project["id"],"T1")["pr_number"]==4
