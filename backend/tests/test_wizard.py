import json

from backend.projects.analyzer import analyze
from backend.prompts import generator
from backend.roadmap import engine

PARAMS = {"name": "Космо", "slug": "kosmo", "kind": "game", "repo_full_name": "owner/kosmo",
          "description": "Аркада", "goals": "Весело"}


def test_analyze_detects_stack():
    a = analyze([{"path": "project.godot", "type": "blob"}, {"path": "README.md", "type": "blob"},
                 {"path": ".github/workflows/ci.yml", "type": "blob"}])
    assert a["recommended_template"] == "godot" and a["recommended_kind"] == "game"
    assert a["existing_portal_files"] == ["README.md"]
    assert analyze([{"path": "app/src/main/AndroidManifest.xml", "type": "blob"}])["recommended_kind"] == "android"
    assert analyze([{"path": "package.json", "type": "blob"}])["recommended_template"] == "web"


def test_generated_files_complete_and_valid():
    files = generator.project_files({**PARAMS, "template": "godot", "default_branch": "main"}, {})
    for f in ("README.md", "docs/AI_RULES.md", "docs/DIRECTOR_HANDOVER.md", "docs/PORTAL_PROTOCOL.md", "docs/GDD.md",
              "docs/gdd/DECISIONS_APPROVED.md", "docs/WORK_PLAN.md", "docs/work_plan.json", "docs/EXECUTOR_RULES.md",
              "tools/work_plan.py", ".github/workflows/nexus-checks.yml"):
        assert files[f].strip()
    engine.check(json.loads(files["docs/work_plan.json"]))
    assert "def main" in files["tools/work_plan.py"]
    for kind in ("android", "web", "server", "other"):
        engine.check(generator.initial_plan({**PARAMS, "kind": kind}))


def test_bootstrap_prompt():
    t = generator.director_bootstrap_prompt({**PARAMS, "template": "godot"})
    assert "ИИ-директор" in t and "work_plan.json" in t and "платные ИИ API" in t


def test_preview_never_overwrites(authed, fake_gh):
    fake_gh.add_repo("owner/kosmo", {"README.md": "# мой README", "project.godot": "x"})
    r = authed.post("/api/wizard/preview", json={"params": PARAMS})
    assert r.status_code == 200, r.text
    data = r.json()
    actions = {c["path"]: c["action"] for c in data["changes"]}
    assert actions["README.md"] == "skip_exists"
    assert actions["docs/AI_RULES.md"] == "create"
    assert data["analysis"]["recommended_template"] == "godot"
    readme = next(c for c in data["changes"] if c["path"] == "README.md")
    assert "мой README" in readme["diff"]

    r = authed.post("/api/wizard/apply", json={"params": PARAMS, "digest": data["digest"]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert "README.md" in res["skipped"] and "README.md" not in res["written"]
    assert "docs/GDD.md" in res["written"]
    assert res["pull_request"]["number"] == 1
    assert fake_gh.files[("owner/kosmo", "main", "README.md")] == "# мой README"  # основная ветка не тронута
    assert ("owner/kosmo", "main", "docs/GDD.md") not in fake_gh.files
    pid = res["project"]["id"]
    rm = authed.get(f"/api/projects/{pid}/roadmap").json()
    assert rm["ready"] == ["T0"]
    assert authed.get(f"/api/projects/{pid}").json()["required_checks"] == ["nexus-plan"]


def test_apply_rejects_stale_preview(authed, fake_gh):
    fake_gh.add_repo("owner/kosmo", {"README.md": "x"})
    digest = authed.post("/api/wizard/preview", json={"params": PARAMS}).json()["digest"]
    fake_gh.files[("owner/kosmo", "main", "docs/GDD.md")] = "изменено"
    r = authed.post("/api/wizard/apply", json={"params": PARAMS, "digest": digest})
    assert r.status_code == 400 and "изменился" in r.json()["detail"]


def test_create_new_repo(authed, fake_gh):
    params = {**PARAMS, "repo_full_name": "owner/newgame", "slug": "newgame"}
    r = authed.post("/api/wizard/apply", json={"params": params, "create_repo": True})
    assert r.status_code == 200, r.text
    assert "owner/newgame" in fake_gh.repos
    assert "docs/AI_RULES.md" in r.json()["written"]


def test_local_project_and_validation(authed):
    r = authed.post("/api/wizard/apply", json={"params": {**PARAMS, "repo_full_name": "", "slug": "local-x"}})
    assert r.status_code == 200
    assert authed.post("/api/wizard/apply", json={"params": {**PARAMS, "repo_full_name": "", "slug": "local-x"}}).status_code == 400
    assert authed.post("/api/wizard/preview", json={"params": {**PARAMS, "slug": "Bad Slug"}}).status_code == 400
    pid = r.json()["project"]["id"]
    pr = authed.get(f"/api/projects/{pid}/prompts").json()
    assert "ИИ-директор" in pr["bootstrap"] and "docs/AI_RULES.md" in pr["files"]
