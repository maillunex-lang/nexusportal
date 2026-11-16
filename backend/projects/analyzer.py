"""Анализ структуры существующего репозитория и выбор шаблона."""
from __future__ import annotations

KINDS = {
    "game": "Игра",
    "android": "Android-приложение",
    "web": "Сайт / веб-приложение",
    "server": "Сервер / backend",
    "other": "Другой программный проект",
}
TEMPLATES = {
    "universal": "Универсальный",
    "godot": "Godot (игры)",
    "android": "Android (Gradle)",
    "web": "Веб (Node.js)",
    "backend": "Backend (Python/Go/Node)",
}
KIND_DEFAULT_TEMPLATE = {"game": "godot", "android": "android", "web": "web", "server": "backend", "other": "universal"}

SIGNS = [
    ("project.godot", "godot", "Godot"),
    ("settings.gradle", "android", "Gradle"),
    ("settings.gradle.kts", "android", "Gradle (Kotlin DSL)"),
    ("app/src/main/AndroidManifest.xml", "android", "Android"),
    ("package.json", "web", "Node.js"),
    ("vite.config.ts", "web", "Vite"),
    ("next.config.js", "web", "Next.js"),
    ("pyproject.toml", "backend", "Python"),
    ("requirements.txt", "backend", "Python"),
    ("go.mod", "backend", "Go"),
    ("Cargo.toml", "backend", "Rust"),
    ("Dockerfile", "backend", "Docker"),
    ("ProjectSettings/ProjectVersion.txt", "universal", "Unity"),
]
PORTAL_FILES = ["README.md", "docs/AI_RULES.md", "docs/DIRECTOR_HANDOVER.md", "docs/PORTAL_PROTOCOL.md",
                "docs/GDD.md", "docs/gdd/DECISIONS_APPROVED.md", "docs/WORK_PLAN.md", "docs/work_plan.json",
                "docs/EXECUTOR_RULES.md", "tools/work_plan.py", ".github/workflows/nexus-checks.yml"]


def analyze(tree: list[dict]) -> dict:
    paths = [t["path"] for t in tree if t.get("type") in ("blob", None)]
    pset = set(paths)
    stack, votes = [], {}
    for sign, tpl, label in SIGNS:
        if sign in pset or any(p.endswith("/" + sign) for p in paths):
            stack.append(label)
            votes[tpl] = votes.get(tpl, 0) + 1
    if "godot" in votes:
        template = "godot"
    elif "android" in votes:
        template = "android"
    elif votes:
        template = max(votes, key=votes.get)
    else:
        template = "universal"
    kind = {"godot": "game", "android": "android", "web": "web", "backend": "server"}.get(template, "other")
    workflows = [p for p in paths if p.startswith(".github/workflows/")]
    top = sorted({p.split("/")[0] for p in paths})[:60]
    return {
        "files_total": len(paths),
        "top_level": top,
        "stack": stack,
        "recommended_template": template,
        "recommended_kind": kind,
        "workflows": workflows,
        "existing_portal_files": [p for p in PORTAL_FILES if p in pset],
        "empty": len(paths) <= 2,
    }
