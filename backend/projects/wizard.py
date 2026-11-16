"""Мастер создания/подключения проекта: предпросмотр и безопасная запись файлов через GitHub API.

Существующие файлы никогда не перезаписываются: в предпросмотре они помечаются «существует — пропуск»,
а при записи используется создание без sha, которое GitHub отклоняет для существующего пути.
Запись идёт в отдельную ветку с Pull Request, основная ветка не меняется напрямую.
"""
from __future__ import annotations

import difflib
import json
import hashlib
import re
import time

from ..core.audit import audit
from ..github.client import GitHubError
from ..memory import service as memory
from ..prompts import generator
from ..roadmap import service as roadmap
from .analyzer import KIND_DEFAULT_TEMPLATE, KINDS, TEMPLATES, analyze

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


class WizardError(ValueError):
    pass


def validate_params(p: dict) -> dict:
    out = {
        "name": (p.get("name") or "").strip()[:100],
        "slug": (p.get("slug") or "").strip().lower(),
        "kind": p.get("kind") or "other",
        "template": p.get("template") or "",
        "description": (p.get("description") or "").strip()[:2000],
        "repo_full_name": (p.get("repo_full_name") or "").strip(),
        "default_branch": (p.get("default_branch") or "main").strip(),
        "goals": (p.get("goals") or "").strip()[:4000],
        "audience": (p.get("audience") or "").strip()[:1000],
        "platforms": (p.get("platforms") or "").strip()[:500],
        "stack": (p.get("stack") or "").strip()[:500],
    }
    if not out["name"]:
        raise WizardError("Укажите название проекта")
    if not SLUG_RE.match(out["slug"]):
        raise WizardError("Идентификатор (slug): латиница в нижнем регистре, цифры и дефис, 2–41 символ")
    if out["kind"] not in KINDS:
        raise WizardError("Неизвестный тип проекта")
    if not out["template"]:
        out["template"] = KIND_DEFAULT_TEMPLATE[out["kind"]]
    if out["template"] not in TEMPLATES:
        raise WizardError("Неизвестный шаблон")
    if out["repo_full_name"] and not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", out["repo_full_name"]):
        raise WizardError("Репозиторий в формате владелец/имя")
    if not re.match(r"^[A-Za-z0-9._/-]{1,100}$", out["default_branch"]):
        raise WizardError("Некорректная основная ветка")
    return out


def build_preview(gh, params: dict) -> dict:
    """Проанализировать репозиторий и построить список изменений."""
    p = validate_params(params)
    analysis = {"empty": True, "existing_portal_files": [], "files_total": 0, "stack": [],
                "recommended_template": p["template"], "recommended_kind": p["kind"], "workflows": [], "top_level": []}
    tree_paths: set[str] = set()
    repo_exists = False
    if p["repo_full_name"]:
        try:
            info = gh.repo(p["repo_full_name"])
            repo_exists = True
            p["default_branch"] = info.get("default_branch") or p["default_branch"]
            tree = gh.tree(p["repo_full_name"], p["default_branch"])
            analysis = analyze(tree)
            tree_paths = {t["path"] for t in tree}
        except GitHubError as e:
            if e.status != 404:
                raise
    files = generator.project_files(p, analysis)
    changes = []
    for path, content in files.items():
        if path in tree_paths:
            existing = gh.get_file(p["repo_full_name"], path, p["default_branch"])
            diff = ""
            if existing:
                diff = "".join(difflib.unified_diff(existing[0].splitlines(True), content.splitlines(True),
                                                    f"a/{path}", f"b/{path} (предложение портала)", n=1))[:6000]
            changes.append({"path": path, "action": "skip_exists", "content": content, "diff": diff,
                            "note": "Файл уже существует — портал его не изменит"})
        else:
            changes.append({"path": path, "action": "create", "content": content, "diff": "",
                            "note": "Будет создан"})
    digest = hashlib.sha256("".join(c["path"] + c["action"] + c["content"] for c in changes).encode()).hexdigest()
    return {"params": p, "repo_exists": repo_exists, "analysis": analysis, "changes": changes, "digest": digest,
            "bootstrap_prompt": generator.director_bootstrap_prompt(p)}


def apply(portal, params: dict, digest: str, *, create_repo: bool = False, private: bool = True,
          actor: str = "owner") -> dict:
    """Записать только отсутствующие файлы (ветка + PR) и зарегистрировать проект в портале."""
    gh = portal.github()
    p = validate_params(params)
    if portal.db.one("SELECT 1 AS x FROM projects WHERE slug=?", (p["slug"],)):
        raise WizardError("Проект с таким идентификатором уже существует")
    if create_repo:
        if not p["repo_full_name"]:
            raise WizardError("Укажите имя нового репозитория владелец/имя")
        owner, name = p["repo_full_name"].split("/")
        me = gh.me()
        created = gh.create_repo(name, private=private, description=p["description"][:300],
                                 org=None if owner.lower() == me["login"].lower() else owner)
        p["repo_full_name"] = created["full_name"]
        p["default_branch"] = created.get("default_branch") or "main"
        for _ in range(10):  # auto_init: ждём первый коммит
            try:
                gh.branch_sha(p["repo_full_name"], p["default_branch"])
                break
            except GitHubError:
                time.sleep(1)
    preview = build_preview(gh, p)
    if preview["digest"] != digest and not create_repo:
        raise WizardError("Репозиторий изменился после предпросмотра — обновите предпросмотр")
    p = preview["params"]
    written, skipped, pr = [], [], None
    warnings = []
    to_create = [c for c in preview["changes"] if c["action"] == "create"]
    if p["repo_full_name"] and to_create:
        base_sha = gh.branch_sha(p["repo_full_name"], p["default_branch"])
        branch = f"nexus/bootstrap-{int(time.time())}"
        gh.create_branch(p["repo_full_name"], branch, base_sha)
        for c in to_create:
            if gh.get_file(p["repo_full_name"], c["path"], branch) is not None:
                skipped.append(c["path"])  # появился после предпросмотра — не трогаем
                continue
            try:
                gh.create_file(p["repo_full_name"], c["path"], c["content"], f"NEXUS PORTAL: добавить {c['path']}", branch)
            except GitHubError as exc:
                if c["path"].startswith(".github/workflows/") and exc.status == 403:
                    skipped.append(c["path"])
                    warnings.append("GitHub запретил запись workflow: " + c["path"] + ". Проверьте разрешение Workflows у токена.")
                    continue
                raise
            written.append(c["path"])
        if written:
            pr = gh.create_pr(p["repo_full_name"], branch, p["default_branch"],
                              "NEXUS PORTAL: подключение проекта",
                              "Портал добавил только отсутствующие файлы:\n" + "\n".join(f"- `{w}`" for w in written)
                              + "\n\nСуществующие файлы не изменялись.")
    skipped += [c["path"] for c in preview["changes"] if c["action"] == "skip_exists"]
    pid = portal.db.insert("projects", {
        "slug": p["slug"], "name": p["name"], "kind": p["kind"], "template": p["template"],
        "repo_full_name": p["repo_full_name"] or None, "default_branch": p["default_branch"],
        "description": p["description"],
        "required_checks": '["nexus-plan"]' if any(c["path"] == ".github/workflows/nexus-checks.yml" and c["action"] == "create" for c in preview["changes"]) else "[]",
    })
    project = portal.project(pid)
    plan = generator.initial_plan(p)
    portal.db.execute("UPDATE projects SET context_index=? WHERE id=?",
                      (json.dumps(generator.modules_index(p, plan), ensure_ascii=False), pid))
    roadmap.import_plan(portal.db, project, plan)
    memory.add(portal.db, pid, "context", "Проект создан мастером",
               f"Тип: {KINDS[p['kind']]}; шаблон: {TEMPLATES[p['template']]}; стек: {', '.join(preview['analysis']['stack']) or 'не определён'}")
    for path in ("docs/GDD.md", "docs/AI_RULES.md", "docs/PORTAL_PROTOCOL.md", "docs/DIRECTOR_HANDOVER.md"):
        memory.add(portal.db, pid, "doc", path, "", path)
    audit(portal.db, actor, "project_created", pid, {"repo": p["repo_full_name"], "written": written, "skipped": skipped})
    return {"project": project, "written": written, "skipped": skipped,
            "pull_request": pr and {"number": pr["number"], "html_url": pr["html_url"]},
            "bootstrap_prompt": preview["bootstrap_prompt"]}


def register_local(portal, params: dict, actor: str = "owner") -> dict:
    """Создать проект без GitHub (репозиторий подключится позже)."""
    p = validate_params(params)
    p["repo_full_name"] = ""
    if portal.db.one("SELECT 1 AS x FROM projects WHERE slug=?", (p["slug"],)):
        raise WizardError("Проект с таким идентификатором уже существует")
    pid = portal.db.insert("projects", {"slug": p["slug"], "name": p["name"], "kind": p["kind"],
                                        "template": p["template"], "default_branch": p["default_branch"],
                                        "description": p["description"]})
    project = portal.project(pid)
    plan = generator.initial_plan(p)
    portal.db.execute("UPDATE projects SET context_index=? WHERE id=?",
                      (json.dumps(generator.modules_index(p, plan), ensure_ascii=False), pid))
    roadmap.import_plan(portal.db, project, plan)
    audit(portal.db, actor, "project_created", pid, {"repo": None})
    return {"project": project, "files": generator.project_files(p, {"stack": []}),
            "bootstrap_prompt": generator.director_bootstrap_prompt(p)}
