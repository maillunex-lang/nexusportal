import json

import pytest

from backend.context import engine as ctx
from backend.prompts import generator

INDEX = {
    "project": "P",
    "docs": {
        "gdd.features": {"path": "docs/gdd/02_features.md", "title": "Функции", "summary": "функции"},
        "gdd.ui": {"path": "docs/gdd/04_ui.md", "title": "Интерфейс", "summary": "экраны"},
        "gdd.net": {"path": "docs/gdd/07_net.md", "title": "Сеть", "summary": "сетевой протокол"},
        "gdd.decisions": {"path": "docs/gdd/DECISIONS_APPROVED.md", "title": "Решения", "summary": "решения"},
    },
    "always_docs": ["gdd.decisions"],
    "modules": [
        {"id": "core", "paths": ["src/core/**"], "docs": ["gdd.features"], "contracts": ["docs/contracts/core.md"],
         "tests": ["tests/core/**"], "public": ["Engine.tick()"], "depends_on": []},
        {"id": "net", "paths": ["src/net/**"], "docs": ["gdd.net"], "contracts": ["docs/contracts/net.md"],
         "tests": ["tests/net/**"], "public": ["Net.send()"], "depends_on": ["core"]},
        {"id": "ui", "paths": ["src/ui/**"], "docs": ["gdd.ui"], "contracts": ["docs/contracts/ui.md"],
         "tests": ["tests/ui/**"], "public": [], "depends_on": ["net"]},
    ],
    "critical_rules": ["Протокол сети версионируется."],
}
PLAN = {"project": "P", "tasks": [
    {"id": "A", "title": "Ядро", "file_scope": ["src/core/**"], "depends_on": [], "status": "done"},
    {"id": "B", "title": "Меню", "goal": "Сделать меню", "file_scope": ["src/ui/menu/**"], "depends_on": ["A"],
     "gdd_refs": ["gdd.ui#Экраны"], "done_when": ["CI зелёный"]},
]}


def test_selects_relevant_docs_and_modules():
    sel = ctx.select(INDEX, PLAN, "B", "standard")
    assert sel["modules"] == ["ui"]  # выведено по file_scope
    assert sel["dependency_modules"] == ["net"]  # standard: только прямые зависимости
    assert "gdd.ui#Экраны" in sel["docs"] and "gdd.decisions" in sel["docs"]
    assert "gdd.features" not in sel["docs"]  # нерелевантное не попадает


def test_extended_includes_transitive_deps():
    sel = ctx.select(INDEX, PLAN, "B", "extended")
    assert sel["dependency_modules"] == ["net", "core"]
    assert "gdd.net" in sel["docs"] and "gdd.features" in sel["docs"]


def test_contracts_and_rules_never_dropped():
    brief = ctx.pack(INDEX, PLAN, "B", "brief")
    for needle in ("docs/contracts/ui.md", "docs/contracts/net.md", "Протокол сети версионируется",
                   "Никаких секретов", "PROJECT_INDEX.md", "src/ui/menu/**", "CI зелёный"):
        assert needle in brief


def test_levels_grow():
    sizes = [len(ctx.pack(INDEX, PLAN, "B", lvl)) for lvl in ctx.LEVELS]
    assert sizes[0] < sizes[1] < sizes[2]
    assert "Net.send()" in ctx.pack(INDEX, PLAN, "B", "standard")
    assert "Net.send()" not in ctx.pack(INDEX, PLAN, "B", "brief")


def test_explicit_modules_override():
    plan = {"tasks": [dict(PLAN["tasks"][1], modules=["net"])] + PLAN["tasks"][:1]}
    assert ctx.select(INDEX, plan, "B")["modules"] == ["net"]


def test_excerpt_instead_of_full_doc(tmp_path):
    doc = tmp_path / "docs/gdd/04_ui.md"
    doc.parent.mkdir(parents=True)
    long = "Очень длинный текст. " * 200
    doc.write_text(f"# UI\n\n## Экраны\nГлавное меню с тремя кнопками. {long}\n\n## Другое\nНЕ_ВКЛЮЧАТЬ\n")
    text = ctx.pack(INDEX, PLAN, "B", "standard", tmp_path)
    assert "Главное меню с тремя кнопками" in text
    assert "НЕ_ВКЛЮЧАТЬ" not in text
    assert text.count("Очень длинный текст") < 30  # GDD не дублируется целиком


def test_cycles_detected():
    bad = json.loads(json.dumps(INDEX))
    bad["modules"][0]["depends_on"] = ["ui"]
    res = ctx.check(bad)
    assert any("Цикл" in e for e in res["errors"])


@pytest.mark.parametrize("mut,msg", [
    (lambda i: i["modules"][0]["docs"].append("gdd.none"), "неизвестный документ"),
    (lambda i: i["modules"][0]["depends_on"].append("ghost"), "неизвестная зависимость"),
    (lambda i: i["modules"].append(dict(i["modules"][0])), "Повторяющиеся"),
])
def test_structural_errors(mut, msg):
    bad = json.loads(json.dumps(INDEX))
    mut(bad)
    assert any(msg in e for e in ctx.check(bad)["errors"])


def test_missing_files_reported(tmp_path):
    (tmp_path / "src/core").mkdir(parents=True)
    plan = {"tasks": [{"id": "X", "title": "x", "gdd_refs": ["docs/old.md"], "modules": ["nope"]}]}
    res = ctx.check(INDEX, plan, tmp_path)
    assert any("неизвестный модуль nope" in e for e in res["errors"])
    w = "\n".join(res["warnings"])
    assert "docs/gdd/04_ui.md отсутствует" in w and "src/net/**" in w and "docs/old.md" in w
    assert "src/core/**" not in w


def test_unknown_task_and_level():
    with pytest.raises(ctx.ContextError):
        ctx.pack(INDEX, PLAN, "Z")
    with pytest.raises(ctx.ContextError):
        ctx.pack(INDEX, PLAN, "B", "huge")


def test_generated_project_is_consistent(tmp_path):
    p = {"name": "Игра", "slug": "g", "kind": "game", "template": "godot", "default_branch": "main", "description": ""}
    files = generator.project_files(p, {})
    for path, content in files.items():
        f = tmp_path / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    assert len(files["docs/GDD.md"]) < 1500  # GDD — оглавление, не гигантский файл
    assert sum(1 for k in files if k.startswith("docs/gdd/0")) >= 6
    idx = json.loads(files["docs/context/modules.json"])
    assert not ctx.check(idx, json.loads(files["docs/work_plan.json"]))["errors"]
    assert ctx.main(["--root", str(tmp_path), "check"]) == 0
    assert ctx.main(["--root", str(tmp_path), "pack", "T2", "--level", "brief"]) == 0
    assert ctx.main(["--root", str(tmp_path), "index", "--write"]) == 0
    assert "| gameplay |" in (tmp_path / "docs/PROJECT_INDEX.md").read_text()


def test_context_api(authed, fake_gh):
    params = {"name": "Космо", "slug": "kosmo", "kind": "game", "repo_full_name": ""}
    pid = authed.post("/api/wizard/apply", json={"params": params}).json()["project"]["id"]
    r = authed.get(f"/api/projects/{pid}/tasks/T2/context?level=brief")
    # Without a repository the director must not claim a fresh context.
    assert r.status_code == 503
    from unittest.mock import patch
    verified = dict(repo="o/r", branch="main", main_sha="abc", synced_at="2026-01-01T00:00:00Z", tasks=[], open_prs=[], sync={})
    with patch("backend.github.fresh_context.snapshot", return_value=verified):
        r = authed.get("/api/projects/{}/tasks/T2/context?level=brief".format(pid))
    assert r.status_code == 200 and "docs/gdd/02_features.md" in r.json()["prompt"]
    assert "docs/gdd/04_ui.md" not in r.json()["prompt"]
    assert "abc" in r.json()["prompt"]
    ci = authed.get(f"/api/projects/{pid}/context-index").json()
    assert ci["check"]["errors"] == [] and ci["markdown"]
    bad = ci["index"]
    bad["modules"][0]["depends_on"] = [bad["modules"][-1]["id"]]
    bad["modules"][-1]["depends_on"] = [bad["modules"][0]["id"]]
    assert authed.put(f"/api/projects/{pid}/context-index", json={"index": bad}).status_code == 400
    assert authed.get(f"/api/projects/{pid}/tasks/T2/context?level=huge").status_code == 400


def test_pull_detects_stale_refs(authed, portal, fake_gh):
    from .conftest import make_project
    p = make_project(portal)
    fake_gh.add_repo("owner/game", {"docs/context/modules.json": json.dumps(INDEX),
                                    "docs/gdd/02_features.md": "x", "src/core/a.py": "x"})
    r = authed.post(f"/api/projects/{p['id']}/context-index/pull")
    assert r.status_code == 200
    w = "\n".join(r.json()["check"]["warnings"])
    assert "04_ui.md" in w and "src/net/**" in w and "02_features" not in w
