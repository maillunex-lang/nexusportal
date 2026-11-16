#!/usr/bin/env python3
"""NEXUS Project Blueprint — стандарт nexus-blueprint/1 (только stdlib).

Blueprint — единый JSON, который ИИ-архитектор формирует после утверждения GDD и дорожной карты:
этапы, потоки работ, задачи, зависимости, приоритеты, критерии приёмки и готовые промпты.
Портал НЕ придумывает задачи и НЕ требует структуры папок: он проверяет документ, вычисляет
очерёдность и безопасный параллелизм и оборачивает промпты архитектора в задание для исполнителя.

Файл самодостаточен (можно копировать в проект как tools/blueprint.py).
Команды: validate <файл>, order <файл>, next <файл> [--done ID,...] [--active ID,...], prompt <файл> <ID> [--executor ...]
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

FORMAT = "nexus-blueprint/1"
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,47}$")
PRIORITIES = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
TASK_TYPES = {"feature", "bugfix", "refactor", "infra", "test", "docs", "content", "art", "audio", "research", "release"}
ESTIMATES = {"XS", "S", "M", "L", "XL"}
EXECUTORS = ("claude", "chatgpt", "codex", "generic")
EXECUTOR_LABELS = {"claude": "Claude", "chatgpt": "ChatGPT", "codex": "Codex", "generic": "Исполнитель"}
MIN_PROMPT = 200          # промпт архитектора должен быть подробным
DEFAULT_MAX_PARALLEL = 3


class BlueprintError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:10]))
        self.errors = errors


# ------------------------------------------------------------------ проверка

def _req_str(obj: dict, key: str, where: str, errors: list[str], min_len: int = 1) -> None:
    v = obj.get(key)
    if not isinstance(v, str) or len(v.strip()) < min_len:
        errors.append(f"{where}: поле «{key}» обязательно (строка{f' ≥ {min_len} символов' if min_len > 1 else ''})")


def _str_list(obj: dict, key: str, where: str, errors: list[str], required: bool = False) -> list:
    v = obj.get(key, [] if not required else None)
    if v is None:
        errors.append(f"{where}: поле «{key}» обязательно (список строк)")
        return []
    if not isinstance(v, list) or any(not isinstance(x, str) or not x.strip() for x in v):
        errors.append(f"{where}: «{key}» должно быть списком непустых строк")
        return []
    if required and not v:
        errors.append(f"{where}: «{key}» не может быть пустым")
    return v


def validate(bp: dict) -> dict:
    """Вернуть {"errors": [...], "warnings": [...]}. Ошибки блокируют импорт и утверждение."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(bp, dict):
        return {"errors": ["Корень документа должен быть объектом"], "warnings": []}
    if bp.get("format") != FORMAT:
        errors.append(f"format должен быть «{FORMAT}»")
    if not isinstance(bp.get("blueprint_version"), str) or not re.match(r"^\d+\.\d+(\.\d+)?$", bp.get("blueprint_version", "")):
        errors.append("blueprint_version: версия документа вида 1.0 или 1.2.3")
    project = bp.get("project")
    if not isinstance(project, dict):
        errors.append("project: обязательный объект")
        project = {}
    _req_str(project, "name", "project", errors)
    _req_str(project, "summary", "project", errors)
    sources = bp.get("sources")
    if not isinstance(sources, dict):
        errors.append("sources: обязательный объект (ссылки на утверждённые GDD и дорожную карту)")
        sources = {}
    _str_list(sources, "gdd", "sources", errors, required=True)
    if not sources.get("approved"):
        warnings.append("sources.approved не true: убедитесь, что GDD и дорожная карта утверждены владельцем")
    conv = bp.get("conventions", {})
    if not isinstance(conv, dict):
        errors.append("conventions: объект")
        conv = {}
    if "max_parallel" in conv and (not isinstance(conv["max_parallel"], int) or not 1 <= conv["max_parallel"] <= 20):
        errors.append("conventions.max_parallel: целое 1..20")
    for k in ("required_checks", "definition_of_done", "global_rules"):
        _str_list(conv, k, "conventions", errors)
    bp_ = conv.get("branch_pattern", "task/{id}")
    if not isinstance(bp_, str) or "{id}" not in bp_:
        errors.append("conventions.branch_pattern должен содержать {id}")

    phases = bp.get("phases")
    if not isinstance(phases, list) or not phases:
        errors.append("phases: непустой список этапов")
        phases = []
    phase_ids = []
    for i, ph in enumerate(phases):
        where = f"phases[{i}]"
        if not isinstance(ph, dict):
            errors.append(f"{where}: объект")
            continue
        if not isinstance(ph.get("id"), str) or not ID_RE.match(ph["id"]):
            errors.append(f"{where}: некорректный id")
        else:
            phase_ids.append(ph["id"])
        _req_str(ph, "title", where, errors)
        _str_list(ph, "exit_criteria", where, errors)
    if len(phase_ids) != len(set(phase_ids)):
        errors.append("phases: повторяющиеся id")

    streams = bp.get("workstreams", [])
    stream_ids = []
    if not isinstance(streams, list):
        errors.append("workstreams: список")
        streams = []
    for i, ws in enumerate(streams):
        if not isinstance(ws, dict) or not isinstance(ws.get("id"), str) or not ID_RE.match(ws.get("id", "")):
            errors.append(f"workstreams[{i}]: некорректный id")
            continue
        stream_ids.append(ws["id"])
        _req_str(ws, "title", f"workstreams[{i}]", errors)

    tasks = bp.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append("tasks: непустой список задач")
        tasks = []
    ids = []
    for i, t in enumerate(tasks):
        where = f"tasks[{i}]"
        if not isinstance(t, dict):
            errors.append(f"{where}: объект")
            continue
        tid = t.get("id")
        if not isinstance(tid, str) or not ID_RE.match(tid):
            errors.append(f"{where}: некорректный id {tid!r}")
            continue
        ids.append(tid)
        where = f"задача {tid}"
        _req_str(t, "title", where, errors)
        _req_str(t, "goal", where, errors)
        _req_str(t, "prompt", where, errors, MIN_PROMPT)
        if t.get("phase") not in phase_ids:
            errors.append(f"{where}: phase должен ссылаться на этап из phases")
        if "workstream" in t and t["workstream"] not in stream_ids:
            errors.append(f"{where}: неизвестный workstream {t['workstream']!r}")
        if t.get("priority", "P2") not in PRIORITIES:
            errors.append(f"{where}: priority — одно из P0, P1, P2, P3")
        if "type" in t and t["type"] not in TASK_TYPES:
            errors.append(f"{where}: неизвестный type {t['type']!r}")
        if "estimate" in t and t["estimate"] not in ESTIMATES:
            errors.append(f"{where}: estimate — XS, S, M, L или XL")
        if t.get("executor_hint", "any") not in (*EXECUTORS, "any"):
            errors.append(f"{where}: executor_hint — claude, chatgpt, codex, generic или any")
        _str_list(t, "acceptance_criteria", where, errors, required=True)
        for k in ("depends_on", "conflicts_with", "resources", "gdd_refs", "deliverables", "verification",
                  "scope_hints", "out_of_scope", "risks"):
            _str_list(t, k, where, errors)
        for p in t.get("scope_hints", []) if isinstance(t.get("scope_hints"), list) else []:
            if isinstance(p, str) and (p.startswith("/") or ".." in p.split("/")):
                errors.append(f"{where}: scope_hints должны быть относительными путями без «..»")
        if "status" in t:
            warnings.append(f"{where}: поле status игнорируется — состояние ведёт портал по PR и CI")
        if not t.get("verification"):
            warnings.append(f"{where}: нет verification — как CI проверит результат?")
        if not t.get("gdd_refs"):
            warnings.append(f"{where}: нет ссылок на GDD (gdd_refs)")
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errors.append("tasks: повторяющиеся id " + ", ".join(dup))
    known = set(ids)
    for t in tasks:
        if not isinstance(t, dict) or t.get("id") not in known:
            continue
        for k in ("depends_on", "conflicts_with"):
            for d in t.get(k, []) if isinstance(t.get(k), list) else []:
                if d == t["id"]:
                    errors.append(f"задача {t['id']}: {k} ссылается на саму себя")
                elif d not in known:
                    errors.append(f"задача {t['id']}: {k} — неизвестная задача {d}")
    if not errors:
        cyc = find_cycle(tasks)
        if cyc:
            errors.append("Цикл зависимостей: " + " -> ".join(cyc))
        order = {p: i for i, p in enumerate(phase_ids)}
        by = {t["id"]: t for t in tasks}
        for t in tasks:
            for d in t.get("depends_on", []):
                if order[by[d]["phase"]] > order[t["phase"]]:
                    warnings.append(f"задача {t['id']} (этап {t['phase']}) зависит от {d} из более позднего этапа {by[d]['phase']}")
    return {"errors": errors, "warnings": warnings}


def find_cycle(tasks: list[dict]) -> list[str] | None:
    by = {t["id"]: t for t in tasks}
    state: dict[str, int] = {}
    stack: list[str] = []

    def walk(k: str) -> list[str] | None:
        state[k] = 1
        stack.append(k)
        for d in by[k].get("depends_on", []):
            if state.get(d) == 1:
                return stack[stack.index(d):] + [d]
            if state.get(d) is None:
                r = walk(d)
                if r:
                    return r
        stack.pop()
        state[k] = 2
        return None

    for k in by:
        if state.get(k) is None:
            r = walk(k)
            if r:
                return r
    return None


def ensure_valid(bp: dict) -> dict:
    res = validate(bp)
    if res["errors"]:
        raise BlueprintError(res["errors"])
    return res


# ------------------------------------------------------------------ очерёдность

def topo_order(bp: dict) -> list[str]:
    """Детерминированный топологический порядок: этап, приоритет, критический путь, порядок в документе."""
    tasks = bp["tasks"]
    by = {t["id"]: t for t in tasks}
    pos = {t["id"]: i for i, t in enumerate(tasks)}
    phase_pos = {p["id"]: i for i, p in enumerate(bp["phases"])}
    cp = critical_path_lengths(bp)
    indeg = {k: len(by[k].get("depends_on", [])) for k in by}
    children: dict[str, list[str]] = {k: [] for k in by}
    for t in tasks:
        for d in t.get("depends_on", []):
            children[d].append(t["id"])

    def key(k):
        t = by[k]
        return (phase_pos[t["phase"]], PRIORITIES[t.get("priority", "P2")], -cp[k], pos[k])

    ready = sorted([k for k, n in indeg.items() if n == 0], key=key)
    out = []
    while ready:
        k = ready.pop(0)
        out.append(k)
        for c in children[k]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
        ready.sort(key=key)
    return out


def critical_path_lengths(bp: dict) -> dict[str, int]:
    """Длина самой длинной цепочки задач, которые ждут данную (включая её)."""
    by = {t["id"]: t for t in bp["tasks"]}
    children: dict[str, list[str]] = {k: [] for k in by}
    for t in bp["tasks"]:
        for d in t.get("depends_on", []):
            children[d].append(t["id"])
    memo: dict[str, int] = {}

    def depth(k):
        if k not in memo:
            memo[k] = 1 + max((depth(c) for c in children[k]), default=0)
        return memo[k]

    return {k: depth(k) for k in by}


def _scopes_overlap(a: list[str], b: list[str]) -> bool:
    def base(p):
        parts = []
        for x in p.split("/"):
            if any(c in x for c in "*?["):
                break
            parts.append(x)
        return "/".join(parts)
    for x in a:
        for y in b:
            if x == y or fnmatch.fnmatch(x, y) or fnmatch.fnmatch(y, x):
                return True
            bx, by_ = base(x), base(y)
            if bx and by_ and (bx == by_ or bx.startswith(by_ + "/") or by_.startswith(bx + "/")):
                return True
    return False


def conflict_reason(bp: dict, a: dict, b: dict) -> str | None:
    """Почему задачи a и b нельзя выполнять одновременно (None — можно)."""
    if b["id"] in a.get("conflicts_with", []) or a["id"] in b.get("conflicts_with", []):
        return "архитектор пометил задачи как конфликтующие"
    shared = sorted(set(a.get("resources", [])) & set(b.get("resources", [])))
    if shared:
        return "общий ресурс: " + ", ".join(shared)
    conv = bp.get("conventions", {})
    if not conv.get("parallel_within_workstream", False) and a.get("workstream") and a.get("workstream") == b.get("workstream"):
        return f"один поток работ «{a['workstream']}» выполняется последовательно"
    if a.get("scope_hints") and b.get("scope_hints") and _scopes_overlap(a["scope_hints"], b["scope_hints"]):
        return "пересекаются подсказки области изменений"
    return None


def schedule(bp: dict, state: dict[str, str]) -> dict:
    """state: {task_id: planned|ready|in_progress|blocked|done}. Возвращает план «Что делать сейчас»."""
    by = {t["id"]: t for t in bp["tasks"]}
    order = topo_order(bp)
    pos = {k: i for i, k in enumerate(order)}
    st = {k: state.get(k, "planned") for k in by}
    active = [by[k] for k in order if st[k] in ("in_progress", "blocked")]
    max_par = bp.get("conventions", {}).get("max_parallel", DEFAULT_MAX_PARALLEL)
    candidates = [by[k] for k in order if st[k] in ("planned", "ready")
                  and all(st[d] == "done" for d in by[k].get("depends_on", []))]
    now, deferred = [], []
    slots = max(0, max_par - len(active))
    for t in candidates:
        reason = None
        for o in active + now:
            r = conflict_reason(bp, t, o)
            if r:
                reason = f"конфликт с {o['id']}: {r}"
                break
        if reason is None and len(now) >= slots:
            reason = f"достигнут предел параллельных задач ({max_par})"
        if reason:
            deferred.append({"id": t["id"], "reason": reason})
        else:
            now.append(t)
    waiting = [{"id": k, "waiting_for": [d for d in by[k].get("depends_on", []) if st[d] != "done"]}
               for k in order if st[k] in ("planned", "ready") and any(st[d] != "done" for d in by[k].get("depends_on", []))]
    done = sum(1 for k in by if st[k] == "done")
    phases = []
    for ph in bp["phases"]:
        ids = [t["id"] for t in bp["tasks"] if t["phase"] == ph["id"]]
        phases.append({"id": ph["id"], "title": ph["title"], "total": len(ids),
                       "done": sum(1 for k in ids if st[k] == "done")})
    return {
        "now": [t["id"] for t in now],
        "deferred": deferred,
        "active": [{"id": t["id"], "status": st[t["id"]]} for t in active],
        "waiting": waiting,
        "order": order,
        "progress": {"done": done, "total": len(by), "percent": round(100 * done / len(by)) if by else 0},
        "phases": phases,
        "max_parallel": max_par,
        "position": pos,
    }


# ------------------------------------------------------------------ задание для исполнителя

def branch_for(bp: dict, task: dict) -> str:
    return bp.get("conventions", {}).get("branch_pattern", "task/{id}").replace("{id}", task["id"].lower())


def _bullets(items, empty="—"):
    return "\n".join(f"- {x}" for x in items) if items else f"- {empty}"


def render_assignment(bp: dict, task_id: str, executor: str = "generic", repo: str = "",
                      base_branch: str = "", state: dict[str, str] | None = None) -> str:
    """Обернуть промпт архитектора в стандартное задание. Текст промпта не изменяется."""
    if executor not in EXECUTORS:
        raise BlueprintError([f"Исполнитель: {', '.join(EXECUTORS)}"])
    by = {t["id"]: t for t in bp["tasks"]}
    t = by.get(task_id)
    if not t:
        raise BlueprintError([f"Задача {task_id} не найдена"])
    conv = bp.get("conventions", {})
    proj = bp["project"]
    repo = repo or proj.get("repository", "")
    base = base_branch or proj.get("default_branch", "main")
    branch = branch_for(bp, t)
    state = state or {}
    deps = [f"{d} — {by[d]['title']}" + (f" ({state[d]})" if d in state else "") for d in t.get("depends_on", [])]
    title_pat = conv.get("pr_title_pattern", "[{id}] {title}")
    pr_title = title_pat.replace("{id}", t["id"]).replace("{title}", t["title"])
    intro = {
        "claude": "Ты — Claude, исполнитель задачи. Работай в репозитории самостоятельно: изучи структуру, выбери нужные файлы, внеси изменения, добавь тесты, открой PR.",
        "codex": "Ты — Codex, исполнитель задачи. Работай непосредственно в репозитории: изучи код, внеси изменения, прогони проверки, открой PR.",
        "chatgpt": "Ты — ChatGPT, исполнитель задачи. Если у тебя есть доступ к репозиторию — внеси изменения и открой PR; если нет — запроси у владельца нужные файлы и выдай полные изменения по файлам с инструкцией применения.",
        "generic": "Ты — исполнитель задачи. Самостоятельно изучи репозиторий, определи нужные файлы, внеси изменения с тестами и открой PR.",
    }[executor]
    parts = [
        f"# Задание {t['id']}: {t['title']}",
        intro,
        "",
        "## Проект",
        f"- {proj['name']}: {proj['summary']}",
        f"- Репозиторий: {repo or 'указан владельцем'}; базовая ветка: `{base}`",
        f"- Ветка задачи: `{branch}`; название PR: `{pr_title}`",
        f"- Этап: {t['phase']}" + (f"; поток работ: {t['workstream']}" if t.get("workstream") else "")
        + f"; приоритет: {t.get('priority', 'P2')}",
        "",
        "## Цель",
        t["goal"],
        "",
        "## Задание архитектора",
        t["prompt"].strip(),
    ]
    if t.get("deliverables"):
        parts += ["", "## Результаты", _bullets(t["deliverables"])]
    parts += ["", "## Критерии приёмки", _bullets(t["acceptance_criteria"])]
    if t.get("verification"):
        parts += ["", "## Как проверить (должно выполняться в CI)", _bullets(t["verification"])]
    parts += ["", "## Документы", _bullets(list(bp["sources"].get("gdd", [])) + list(t.get("gdd_refs", [])))]
    parts += ["", "## Выполненные зависимости", _bullets(deps, "нет")]
    if t.get("scope_hints"):
        parts += ["", "## Подсказки по области изменений (не ограничение — проверь по факту)", _bullets(t["scope_hints"])]
    if t.get("out_of_scope"):
        parts += ["", "## Не входит в задачу", _bullets(t["out_of_scope"])]
    if t.get("risks"):
        parts += ["", "## Риски", _bullets(t["risks"])]
    rules = [
        "Сначала изучи README, документы проекта и фактическую структуру репозитория; файлы для изменения определи сам.",
        "Если в репозитории есть docs/PROJECT_INDEX.md — начни с него; не читай весь репозиторий без необходимости.",
        f"Создай ветку `{branch}` от актуальной `{base}`, открой один PR в `{base}`; не сливай его сам.",
        "Задача выполнена, когда обязательный CI зелёный на последнем коммите PR и портал слил PR. Скриншоты не нужны.",
        "Не изменяй чужие задачи и общие документы архитектора (blueprint, GDD), если задача этого не требует.",
        "Никаких секретов, токенов и паролей в коде и PR. Платные ИИ API не использовать.",
    ] + list(conv.get("global_rules", []))
    if conv.get("required_checks"):
        rules.append("Обязательные проверки CI: " + ", ".join(conv["required_checks"]))
    if conv.get("definition_of_done"):
        rules += [f"Definition of Done: {x}" for x in conv["definition_of_done"]]
    parts += ["", "## Правила", _bullets(rules)]
    parts += ["", "## Отчёт в описании PR",
              "- что сделано и почему; изменённые файлы; добавленные тесты и как их запустить; допущения и риски."]
    return "\n".join(parts) + "\n"


# ------------------------------------------------------------------ совместимость

def from_adaptive(plan: dict) -> dict:
    """Конвертировать план Adaptive Project Engine (PR #2, tools/adaptive_project.py) в nexus-blueprint/1.
    Состояния задач не переносятся: их ведёт портал."""
    pr = {3: "P0", 2: "P1", 1: "P2", 0: "P3"}
    tasks = []
    for t in plan.get("tasks", []):
        p = int(t.get("priority", 0) or 0)
        desc = t.get("description") or t.get("title", "")
        tasks.append({
            "id": t["id"], "title": t.get("title", t["id"]), "phase": "main", "priority": pr.get(min(max(p, 0), 3), "P2"),
            "goal": desc, "depends_on": t.get("dependencies", []), "acceptance_criteria": t.get("acceptance", []),
            "verification": t.get("checks", []), "scope_hints": t.get("file_scopes", []), "gdd_refs": [],
            "prompt": (f"Выполни задачу «{t.get('title', t['id'])}». {desc}\n\nИзучи GDD ({', '.join(plan.get('gdd_refs', []))}) и "
                       "фактическую структуру репозитория, определи нужные файлы самостоятельно. "
                       "Выполни все критерии приёмки, добавь автоматические тесты, открой PR. "
                       "Если пути из подсказок не совпадают с репозиторием — не угадывай, опиши расхождение в PR."),
        })
    return {
        "format": FORMAT, "blueprint_version": "1.0",
        "project": {"name": plan.get("project") or plan.get("repository", "Проект"),
                    "summary": "Импортировано из Adaptive Project Engine", "repository": plan.get("repository", ""),
                    "default_branch": plan.get("base_branch", "main")},
        "sources": {"gdd": plan.get("gdd_refs") or ["docs/GDD.md"], "approved": False},
        "conventions": {"max_parallel": DEFAULT_MAX_PARALLEL, "parallel_within_workstream": True},
        "phases": [{"id": "main", "title": "Основной этап"}],
        "workstreams": [],
        "tasks": tasks,
    }


def detect_and_convert(doc: dict) -> tuple[dict, str]:
    if isinstance(doc, dict) and doc.get("format") == FORMAT:
        return doc, "nexus-blueprint/1"
    if isinstance(doc, dict) and "tasks" in doc and "base_branch" in doc and any("acceptance" in t for t in doc.get("tasks", []) if isinstance(t, dict)):
        return from_adaptive(doc), "adaptive-project"
    return doc, "unknown"


# ------------------------------------------------------------------ CLI

def _ids(s: str | None) -> list[str]:
    return [x for x in (s or "").split(",") if x]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NEXUS Project Blueprint")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate", "order"):
        s = sub.add_parser(name); s.add_argument("file")
    n = sub.add_parser("next"); n.add_argument("file"); n.add_argument("--done"); n.add_argument("--active")
    p = sub.add_parser("prompt"); p.add_argument("file"); p.add_argument("task")
    p.add_argument("--executor", default="generic", choices=EXECUTORS)
    a = ap.parse_args(argv)
    try:
        doc, kind = detect_and_convert(json.loads(Path(a.file).read_text(encoding="utf-8")))
        res = validate(doc)
        for w in res["warnings"]:
            print("ПРЕДУПРЕЖДЕНИЕ:", w, file=sys.stderr)
        if res["errors"]:
            for e in res["errors"]:
                print("ОШИБКА:", e, file=sys.stderr)
            return 1
        if a.cmd == "validate":
            print(f"OK ({kind}): этапов {len(doc['phases'])}, задач {len(doc['tasks'])}")
        elif a.cmd == "order":
            print("\n".join(topo_order(doc)))
        elif a.cmd == "next":
            state = {k: "done" for k in _ids(a.done)} | {k: "in_progress" for k in _ids(a.active)}
            r = schedule(doc, state)
            print(json.dumps({k: r[k] for k in ("now", "deferred", "waiting", "progress")}, ensure_ascii=False, indent=2))
        elif a.cmd == "prompt":
            print(render_assignment(doc, a.task, a.executor), end="")
    except (ValueError, OSError) as e:
        print("ОШИБКА:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
