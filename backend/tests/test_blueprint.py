import copy
import json
from pathlib import Path

import pytest

from backend.blueprint import core
from backend.blueprint import service as bps
from backend.orchestration import automerge
from .conftest import make_project

ROOT = Path(__file__).resolve().parents[2]
EX = ROOT / "docs" / "blueprint" / "examples"
SCHEMA = json.loads((ROOT / "docs" / "blueprint" / "blueprint.schema.json").read_text())
LONG = "Подробное задание исполнителю. " * 10


def load(name):
    return json.loads((EX / name).read_text())


def mini(**conv):
    def t(id, phase="A", **kw):
        return {"id": id, "title": f"Задача {id}", "phase": phase, "goal": "цель", "acceptance_criteria": ["ok"],
                "verification": ["tests"], "gdd_refs": ["docs/GDD.md"], "prompt": LONG + id, **kw}
    return {"format": core.FORMAT, "blueprint_version": "1.0", "project": {"name": "P", "summary": "s"},
            "sources": {"gdd": ["docs/GDD.md"], "approved": True}, "conventions": {"max_parallel": 3, **conv},
            "phases": [{"id": "A", "title": "A"}, {"id": "B", "title": "B"}],
            "workstreams": [{"id": "x", "title": "X"}, {"id": "y", "title": "Y"}],
            "tasks": [t("T1", priority="P0"), t("T2", depends_on=["T1"], workstream="x"),
                      t("T3", depends_on=["T1"], workstream="y", priority="P1"),
                      t("T4", depends_on=["T1"], resources=["save"]), t("T5", "B", depends_on=["T2", "T3"])]}


# ---------- стандарт и схема

@pytest.mark.parametrize("name", ["game-platformer.json", "android-habits.json", "web-catalog.json"])
def test_examples_valid_against_core_and_schema(name):
    doc = load(name)
    assert core.validate(doc)["errors"] == []
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    jsonschema.validate(doc, SCHEMA)


def test_template_and_prompt_exist():
    tpl = json.loads((ROOT / "docs/blueprint/template.json").read_text())
    assert tpl["format"] == core.FORMAT
    text = (ROOT / "docs/blueprint/ARCHITECT_PROMPT.md").read_text()
    assert "nexus-blueprint/1" in text and "depends_on" in text and "resources" in text


BAD = [
    (lambda d: d.update(format="x"), "format"),
    (lambda d: d["tasks"][1].update(depends_on=["T9"]), "неизвестная задача"),
    (lambda d: d["tasks"][0].update(depends_on=["T5"]), "Цикл"),
    (lambda d: d["tasks"][0].update(acceptance_criteria=[]), "acceptance_criteria"),
    (lambda d: d["tasks"][0].update(prompt="коротко"), "prompt"),
    (lambda d: d["tasks"][0].update(phase="Z"), "phase"),
    (lambda d: d["tasks"][0].update(priority="high"), "priority"),
    (lambda d: d["tasks"][0].update(scope_hints=["../etc"]), "scope_hints"),
    (lambda d: d["tasks"].append(copy.deepcopy(d["tasks"][0])), "повторяющиеся"),
    (lambda d: d["tasks"][0].update(conflicts_with=["T1"]), "саму себя"),
    (lambda d: d.update(phases=[]), "phases"),
]


@pytest.mark.parametrize("mut,msg", BAD)
def test_invalid_documents(mut, msg):
    d = mini()
    mut(d)
    errs = core.validate(d)["errors"]
    assert any(msg in e for e in errs), errs


@pytest.mark.parametrize("mut,msg", [b for b in BAD if b[1] not in ("неизвестная задача", "Цикл", "повторяющиеся", "саму себя", "phase")])
def test_schema_agrees_on_structural_errors(mut, msg):
    jsonschema = pytest.importorskip("jsonschema")
    d = mini()
    mut(d)
    assert list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(d))


def test_warnings_not_errors():
    d = mini()
    d["tasks"][0]["status"] = "done"
    d["tasks"][0].pop("verification")
    r = core.validate(d)
    assert not r["errors"] and any("status" in w for w in r["warnings"]) and any("verification" in w for w in r["warnings"])


# ---------- очерёдность и параллелизм

def test_topo_order_respects_deps_and_priority():
    order = core.topo_order(mini())
    assert order[0] == "T1" and order[-1] == "T5"
    assert order.index("T2") < order.index("T5") and order.index("T3") < order.index("T5")
    # P1 выше P2 при равных этапах
    assert order.index("T3") < order.index("T4")


def test_schedule_ready_and_waiting():
    s = core.schedule(mini(), {})
    assert s["now"] == ["T1"]
    assert {w["id"] for w in s["waiting"]} == {"T2", "T3", "T4", "T5"}
    s = core.schedule(mini(), {"T1": "done"})
    assert set(s["now"]) == {"T2", "T3", "T4"}
    assert s["progress"] == {"done": 1, "total": 5, "percent": 20}


def test_resource_conflict_with_active_task():
    d = mini()
    d["tasks"][1]["resources"] = ["save"]
    s = core.schedule(d, {"T1": "done", "T4": "in_progress"})
    assert "T2" not in s["now"] and any(x["id"] == "T2" and "save" in x["reason"] for x in s["deferred"])


def test_conflicts_with_and_workstream_serial():
    d = mini()
    d["tasks"][2]["conflicts_with"] = ["T4"]
    d["tasks"].append({**copy.deepcopy(d["tasks"][1]), "id": "T6"})
    s = core.schedule(d, {"T1": "done"})
    assert "T6" not in s["now"]  # тот же поток x, что и T2
    assert any(x["id"] == "T6" and "поток" in x["reason"] for x in s["deferred"])
    assert not ({"T3", "T4"} <= set(s["now"]))
    d["conventions"]["parallel_within_workstream"] = True
    assert "T6" in core.schedule(d, {"T1": "done"})["now"]


def test_max_parallel_and_scope_hints():
    d = mini(max_parallel=1)
    s = core.schedule(d, {"T1": "done"})
    assert len(s["now"]) == 1 and any("предел" in x["reason"] for x in s["deferred"])
    d = mini()
    d["tasks"][2]["scope_hints"] = ["src/ui/**"]
    d["tasks"][3]["scope_hints"] = ["src/ui/menu.ts"]
    s = core.schedule(d, {"T1": "done"})
    assert not ({"T3", "T4"} <= set(s["now"]))


# ---------- задания

@pytest.mark.parametrize("executor,needle", [("claude", "Claude"), ("chatgpt", "ChatGPT"), ("codex", "Codex"), ("generic", "исполнитель")])
def test_assignment_wraps_architect_prompt(executor, needle):
    d = load("game-platformer.json")
    text = core.render_assignment(d, "G02", executor, "owner/game", "main", {"G01": "done"})
    t = next(t for t in d["tasks"] if t["id"] == "G02")
    assert t["prompt"].strip() in text  # промпт архитектора не изменяется
    for s in (needle, "task/g02", "[G02] Контроллер персонажа", "owner/game", "Критерии приёмки", "G01 — Каркас проекта Godot и CI (done)",
              "файлы для изменения определи сам", "Никаких секретов", "godot-tests"):
        assert s in text
    with pytest.raises(core.BlueprintError):
        core.render_assignment(d, "G02", "gpt5")


def test_adaptive_project_plan_converted():
    plan = {"repository": "owner/game", "base_branch": "main", "gdd_refs": ["docs/GDD.md"],
            "tasks": [{"id": "a", "title": "Ядро", "acceptance": ["работает"], "dependencies": [], "file_scopes": ["src/core/**"], "priority": 3},
                      {"id": "b", "title": "UI", "acceptance": ["есть меню"], "dependencies": ["a"], "status": "accepted"}]}
    doc, kind = core.detect_and_convert(plan)
    assert kind == "adaptive-project" and core.validate(doc)["errors"] == []
    assert doc["tasks"][0]["priority"] == "P0" and doc["tasks"][1]["depends_on"] == ["a"]
    assert "status" not in doc["tasks"][1]


def test_cli(tmp_path, capsys):
    f = EX / "game-platformer.json"
    assert core.main(["validate", str(f)]) == 0
    assert core.main(["next", str(f), "--done", "G01"]) == 0
    assert '"G02"' in capsys.readouterr().out
    assert core.main(["prompt", str(f), "G03", "--executor", "claude"]) == 0
    bad = tmp_path / "b.json"
    bad.write_text("{}")
    assert core.main(["validate", str(bad)]) == 1


# ---------- портал: импорт, утверждение, версии, выполнение

def setup(portal, fake_gh):
    fake_gh.add_repo("owner/game")
    return make_project(portal, required_checks="[]")


def test_import_approve_and_now(authed, portal, fake_gh):
    p = setup(portal, fake_gh)
    doc = load("game-platformer.json")
    r = authed.post("/api/blueprint/validate", json={"document": doc}).json()
    assert r["errors"] == [] and r["order"][0] == "G01"
    bad = copy.deepcopy(doc); bad["tasks"][0]["depends_on"] = ["G08"]
    r = authed.post(f"/api/projects/{p['id']}/blueprints", json={"document": bad})
    assert r.status_code == 400 and any("Цикл" in e for e in r.json()["detail"]["errors"])
    v1 = authed.post(f"/api/projects/{p['id']}/blueprints", json={"document": doc}).json()
    assert v1["version"] == 1 and v1["status"] == "draft" and len(v1["changes"]["added"]) == 8
    again = authed.post(f"/api/projects/{p['id']}/blueprints", json={"document": doc}).json()
    assert again["id"] == v1["id"]  # тот же документ — та же версия
    assert authed.get(f"/api/projects/{p['id']}/now").json()["blueprint"] is None
    assert authed.post(f"/api/projects/{p['id']}/blueprints/{v1['id']}/approve", json={}).status_code == 200
    n = authed.get(f"/api/projects/{p['id']}/now").json()
    assert [c["id"] for c in n["now"]] == ["G01"] and n["progress"]["total"] == 8
    rm = authed.get(f"/api/projects/{p['id']}/roadmap").json()
    assert rm["plan"]["stages"][0]["id"] == "P1" and len(rm["plan"]["tasks"]) == 8
    proj = authed.get(f"/api/projects/{p['id']}").json()
    assert proj["required_checks"] == ["godot-tests", "export-check"]
    a = authed.get(f"/api/projects/{p['id']}/tasks/G01/assignment?executor=claude").json()["prompt"]
    assert "Ты — Claude" in a and "task/g01" in a
    assert "Каркас проекта Godot" in authed.get(f"/api/projects/{p['id']}/tasks/G01/prompt").json()["prompt"]
    assert authed.get("/api/now").json()[0]["now"][0]["id"] == "G01"
    std = authed.get("/api/blueprint/standard").json()
    assert std["schema"] and std["architect_prompt"] and std["template"]


def test_pr_ci_merge_flow_updates_now_and_history(portal, fake_gh):
    p = setup(portal, fake_gh)
    portal.db.execute("UPDATE projects SET auto_merge_enabled=1 WHERE id=?", (p["id"],))
    v = bps.submit(portal, p, load("game-platformer.json"))
    bps.approve(portal, portal.project(p["id"]), v["id"])
    p = portal.project(p["id"])
    sha = "c" * 40
    fake_gh.add_pr("owner/game", 7, "task/g01", sha, "[G01] Каркас")
    fake_gh.set_check("owner/game", sha, "godot-tests", "failure")
    fake_gh.set_check("owner/game", sha, "export-check", "success")
    assert automerge.process_pr(portal, p, 7)["decision"] == "ci_failed"
    n = bps.now(portal, p)
    assert n["attention"][0]["id"] == "G01" and n["attention"][0]["pr"]["number"] == 7
    assert "Исправь ошибку CI" in bps.assignment(portal, p, "G01", "claude")
    new = "d" * 40
    fake_gh.prs[("owner/game", 7)]["head"]["sha"] = new
    fake_gh.set_check("owner/game", new, "godot-tests", "success")
    fake_gh.set_check("owner/game", new, "export-check", "success")
    assert automerge.process_pr(portal, p, 7)["decision"] == "merged"
    n = bps.now(portal, p)
    assert set(c["id"] for c in n["now"]) == {"G02", "G03", "G05"} and n["progress"]["done"] == 1
    events = [e["event"] for e in bps.history(portal, p, "G01")]
    for e in ("merged", "ci_failed", "pr_opened", "task_added", "assignment_copied", "pr_updated"):
        assert e in events, events


def test_new_version_keeps_progress_and_tracks_changes(authed, portal, fake_gh):
    p = setup(portal, fake_gh)
    doc = load("game-platformer.json")
    v1 = bps.submit(portal, p, doc)
    bps.approve(portal, portal.project(p["id"]), v1["id"])
    from backend.roadmap import service as roadmap
    roadmap.set_status(portal.db, p, "G01", "done", confirmed_merge=True)
    roadmap.set_status(portal.db, p, "G03", "in_progress")
    d2 = copy.deepcopy(doc)
    d2["blueprint_version"] = "1.1"
    d2["tasks"] = [t for t in d2["tasks"] if t["id"] != "G03"]
    next(t for t in d2["tasks"] if t["id"] == "G07")["depends_on"] = ["G02", "G05"]
    d2["tasks"][0]["title"] = "Каркас (уточнено)"
    d2["tasks"].append({**copy.deepcopy(d2["tasks"][-1]), "id": "G09", "title": "Аналитика", "depends_on": ["G01"]})
    v2 = bps.submit(portal, portal.project(p["id"]), d2)
    assert v2["version"] == 2 and v2["changes"]["added"] == ["G09"] and v2["changes"]["removed"] == ["G03"]
    assert {"id": "G01", "fields": ["title"]} in v2["changes"]["changed"]
    r = authed.post(f"/api/projects/{p['id']}/blueprints/{v2['id']}/approve", json={})
    assert r.status_code == 400 and "G03" in str(r.json())  # задача в работе не удаляется молча
    assert authed.post(f"/api/projects/{p['id']}/blueprints/{v2['id']}/approve", json={"force": True}).status_code == 200
    assert roadmap.get_task(portal.db, p["id"], "G01")["status"] == "done"  # прогресс сохранён
    assert roadmap.get_task(portal.db, p["id"], "G03") is None
    vs = authed.get(f"/api/projects/{p['id']}/blueprints").json()
    assert [(v["version"], v["status"]) for v in vs] == [(2, "approved"), (1, "superseded")]
    ev = {(e["task_id"], e["event"]) for e in bps.history(portal, p)}
    assert ("G03", "task_removed") in ev and ("G09", "task_added") in ev and ("G01", "task_changed") in ev
    assert "G09" in [c["id"] for c in bps.now(portal, portal.project(p["id"]))["now"]]


def test_reject_and_pull_from_github(authed, portal, fake_gh):
    p = setup(portal, fake_gh)
    fake_gh.files[("owner/game", "main", "docs/blueprint.json")] = json.dumps(load("android-habits.json"))
    r = authed.post(f"/api/projects/{p['id']}/blueprints/pull", json={})
    assert r.status_code == 200 and r.json()["source"].startswith("GitHub docs/blueprint.json")
    assert authed.post(f"/api/projects/{p['id']}/blueprints/{r.json()['id']}/reject").status_code == 200
    assert authed.post(f"/api/projects/{p['id']}/blueprints/{r.json()['id']}/approve", json={}).status_code == 400
    assert authed.post(f"/api/projects/{p['id']}/blueprints/pull", json={"path": "../x"}).status_code == 400
    assert authed.post(f"/api/projects/{p['id']}/blueprints", json={"document": {"foo": 1}}).status_code == 400
