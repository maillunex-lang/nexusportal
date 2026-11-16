import json

import pytest
from unittest.mock import patch

from backend.roadmap import engine, service
from .conftest import make_project


def plan(**over):
    p = {"project": "P", "repo": "o/r", "stages": [{"id": "S1", "title": "Этап"}], "tasks": [
        {"id": "A", "title": "Основа", "stage": "S1", "lane": "core", "file_scope": ["src/core/**"]},
        {"id": "B", "title": "UI", "stage": "S1", "lane": "ui", "depends_on": ["A"], "file_scope": ["src/ui/**"]},
        {"id": "C", "title": "Данные", "stage": "S1", "lane": "data", "depends_on": ["A"]},
        {"id": "D", "title": "Релиз", "stage": "S1", "lane": "release", "depends_on": ["B", "C"]},
    ]}
    p.update(over)
    return p


def test_check_and_topology():
    order = engine.check(plan())
    assert order.index("A") < order.index("B") < order.index("D")


@pytest.mark.parametrize("mut,msg", [
    (lambda p: p["tasks"][0].update(depends_on=["D"]), "Цикл"),
    (lambda p: p["tasks"][1].update(depends_on=["Z"]), "отсутствует"),
    (lambda p: p["tasks"].append({"id": "A", "title": "dup"}), "Повторяющиеся"),
    (lambda p: p["tasks"][0].update(status="weird"), "статус"),
    (lambda p: p["tasks"][0].update(stage="S9"), "этап"),
    (lambda p: p["tasks"][1].update(status="done"), "не done"),
])
def test_check_errors(mut, msg):
    p = plan()
    mut(p)
    with pytest.raises(engine.PlanError, match=msg):
        engine.check(p)


def test_ready_and_parallel_lanes():
    p = engine.normalize(plan())
    assert [t["id"] for t in engine.ready(p)] == ["A"]
    p["tasks"][0]["status"] = "done"
    assert [t["id"] for t in engine.ready(p)] == ["B", "C"]  # параллельные линии
    changed = engine.refresh_ready(p)
    assert set(changed) == {"B", "C"}
    assert engine.lanes(p)["ui"] == ["B"]


def test_prompt_contents():
    p = engine.normalize(plan())
    p["tasks"][0]["status"] = "done"
    text = engine.prompt(p, "B")
    for needle in ("Задача B: UI", "Цель", "docs/GDD.md", "src/ui/**", "task/b", "Критерии готовности",
                   "A — Основа (done)", "Параллельно могут выполняться: C"):
        assert needle in text


def test_set_done_forbidden():
    with pytest.raises(engine.PlanError):
        engine.set_status(engine.normalize(plan()), "A", "done")


def test_cli_commands(tmp_path, capsys):
    f = tmp_path / "work_plan.json"
    f.write_text(json.dumps(plan(), ensure_ascii=False))
    assert engine.main(["--file", str(f), "check"]) == 0
    assert engine.main(["--file", str(f), "next"]) == 0
    assert "A\tcore" in capsys.readouterr().out
    assert engine.main(["--file", str(f), "prompt", "D"]) == 0
    assert engine.main(["--file", str(f), "render", "--write", str(tmp_path / "W.md")]) == 0
    assert "| D | Релиз |" in (tmp_path / "W.md").read_text()
    assert engine.main(["--file", str(f), "set", "A", "done"]) == 1
    assert engine.main(["--file", str(f), "set", "A", "in_progress"]) == 0
    assert json.loads(f.read_text())["tasks"][0]["status"] == "in_progress"


def test_legacy_packages_format():
    data = {"project": "X", "packages": [{"id": "N1", "title": "a", "depends_on": [], "status": "planned", "done_when": []}]}
    assert engine.check(data) == ["N1"]


def test_repo_work_plan_valid():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    data = engine.load(root / "docs" / "work_plan.json")
    engine.check(data)
    assert {t["id"] for t in data["tasks"]} >= {f"N{i}" for i in range(1, 11)}


def test_service_import_refresh_and_done_guard(portal):
    pr = make_project(portal)
    p = plan()
    p["tasks"][0]["status"] = "done"  # done из файла не принимается без слияния
    out = service.import_plan(portal.db, pr, p)
    assert {t["id"]: t["status"] for t in out["tasks"]}["A"] == "ready"
    with pytest.raises(engine.PlanError):
        service.set_status(portal.db, pr, "A", "done")
    service.set_status(portal.db, pr, "A", "done", confirmed_merge=True)
    assert set(service.refresh(portal.db, pr)) == {"B", "C"}
    # повторный импорт не сбрасывает done
    out = service.import_plan(portal.db, pr, plan())
    assert {t["id"]: t["status"] for t in out["tasks"]}["A"] == "done"


def test_roadmap_api(authed, portal):
    pr = make_project(portal)
    assert authed.put(f"/api/projects/{pr['id']}/roadmap", json={"plan": plan()}).status_code == 200
    bad = plan()
    bad["tasks"][0]["depends_on"] = ["D"]
    assert authed.put(f"/api/projects/{pr['id']}/roadmap", json={"plan": bad}).status_code == 400
    r = authed.get(f"/api/projects/{pr['id']}/roadmap").json()
    assert r["ready"] == ["A"]
    assert authed.get(f"/api/projects/{pr.get("id")}/tasks/A/prompt").status_code == 503
    verified = dict(repo="o/r", branch="main", main_sha="abc", synced_at="2026-01-01T00:00:00Z", tasks=[], open_prs=[], sync={})
    with patch("backend.github.fresh_context.snapshot", return_value=verified):
        response = authed.get(f"/api/projects/{pr.get("id")}/tasks/A/prompt")
    assert response.status_code == 200
    assert "Задача A" in response.json()["prompt"]
    assert "abc" in response.json()["prompt"]
    assert authed.post(f"/api/projects/{pr['id']}/tasks/A/status", json={"status": "done"}).status_code == 400
    assert authed.post(f"/api/projects/{pr['id']}/tasks/A/status", json={"status": "in_progress"}).status_code == 200
