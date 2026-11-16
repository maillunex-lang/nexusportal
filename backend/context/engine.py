#!/usr/bin/env python3
"""NEXUS Smart Context: минимальный контекст для ИИ-исполнителя (только stdlib).

Файл самодостаточен: портал копирует его в проекты как ``tools/context_pack.py``.

Источники:
  docs/context/modules.json — машинный индекс: документы, модули, каталоги, контракты, тесты, правила;
  docs/work_plan.json       — задачи (поле ``modules`` необязательно: иначе модули выводятся по file_scope).

Команды:
  pack <ID> [--level brief|standard|extended]  — пакет инструкций для исполнителя
  check                                         — устаревшие ссылки, отсутствующие файлы, циклы
  index [--write]                               — сгенерировать docs/PROJECT_INDEX.md
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

LEVELS = ("brief", "standard", "extended")
INDEX_PATH = "docs/context/modules.json"
PLAN_PATH = "docs/work_plan.json"
PROJECT_INDEX = "docs/PROJECT_INDEX.md"
EXCERPT_CHARS = {"brief": 0, "standard": 300, "extended": 900}

# Правила, которые никогда не вырезаются ради экономии токенов.
BASE_CRITICAL_RULES = [
    "Никаких секретов, токенов, паролей и приватных ключей в коде, коммитах, PR и логах.",
    "Менять только разрешённые файлы задачи; общие файлы (GDD, work_plan.json, индексы) меняет директор.",
    "Не ломать публичные интерфейсы и межмодульные контракты без задачи на их изменение.",
    "Не отключать и не ослаблять тесты и проверки CI.",
]


class ContextError(ValueError):
    pass


# ---------- загрузка и проверка

def load_json(root: Path, rel: str) -> dict:
    p = root / rel
    if not p.exists():
        raise ContextError(f"Не найден {rel}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ContextError(f"{rel}: некорректный JSON ({e})")


def _match(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        base = pattern[:-3]
        return path == base or path.startswith(base + "/")
    return fnmatch.fnmatch(path, pattern)


def _pattern_base(pattern: str) -> str:
    """Каталог/файл без glob-части — для проверки существования."""
    parts = []
    for part in pattern.split("/"):
        if any(c in part for c in "*?["):
            break
        parts.append(part)
    return "/".join(parts)


def _patterns_overlap(a: str, b: str) -> bool:
    ba, bb = _pattern_base(a), _pattern_base(b)
    if not ba or not bb:
        return False
    return ba == bb or ba.startswith(bb + "/") or bb.startswith(ba + "/") or _match(ba, b) or _match(bb, a)


def module_cycles(index: dict) -> list[list[str]]:
    mods = {m["id"]: m for m in index.get("modules", [])}
    cycles, state = [], {}

    def walk(k, path):
        if state.get(k) == 1:
            cycles.append(path[path.index(k):] + [k])
            return
        if state.get(k) == 2 or k not in mods:
            return
        state[k] = 1
        for d in mods[k].get("depends_on", []):
            walk(d, path + [k])
        state[k] = 2

    for k in mods:
        walk(k, [])
    return cycles


def check(index: dict, plan: dict | None = None, root: Path | None = None) -> dict:
    """Вернуть {"errors": [...], "warnings": [...]}. Ошибки — структурные, предупреждения — устаревшие ссылки."""
    errors, warnings = [], []
    docs = index.get("docs", {})
    mods = index.get("modules", [])
    ids = [m.get("id") for m in mods]
    if len(ids) != len(set(ids)):
        errors.append("Повторяющиеся ID модулей")
    known = set(ids)
    for m in mods:
        for d in m.get("docs", []):
            if d not in docs:
                errors.append(f"Модуль {m['id']}: неизвестный документ {d}")
        for d in m.get("depends_on", []):
            if d not in known:
                errors.append(f"Модуль {m['id']}: неизвестная зависимость {d}")
        if not m.get("paths"):
            errors.append(f"Модуль {m['id']}: не указаны каталоги")
    for cyc in module_cycles(index):
        errors.append("Цикл зависимостей модулей: " + " -> ".join(cyc))
    if plan:
        for t in plan.get("tasks", plan.get("packages", [])):
            for mid in t.get("modules", []):
                if mid not in known:
                    errors.append(f"Задача {t['id']}: неизвестный модуль {mid}")
            for ref in t.get("gdd_refs", []):
                key = ref.split("#")[0]
                if key not in docs and not any(d["path"] == key for d in docs.values()) and root and not (root / key).exists():
                    warnings.append(f"Задача {t['id']}: ссылка на отсутствующий документ {ref}")
    if root:
        for key, d in docs.items():
            if not (root / d["path"]).exists():
                warnings.append(f"Документ {key}: файл {d['path']} отсутствует")
        for m in mods:
            for kind in ("paths", "contracts", "tests"):
                for p in m.get(kind, []):
                    base = _pattern_base(p)
                    if base and not (root / base).exists():
                        warnings.append(f"Модуль {m['id']}: {kind} {p} не существует")
    return {"errors": errors, "warnings": warnings}


# ---------- выбор контекста

def task_modules(index: dict, task: dict) -> list[str]:
    explicit = task.get("modules") or []
    if explicit:
        return list(dict.fromkeys(explicit))
    out = []
    for m in index.get("modules", []):
        if any(_patterns_overlap(s, p) for s in task.get("file_scope", []) for p in m.get("paths", [])):
            out.append(m["id"])
    return out


def module_deps(index: dict, start: list[str], transitive: bool) -> list[str]:
    mods = {m["id"]: m for m in index.get("modules", [])}
    seen, order = set(start), []
    frontier = list(start)
    while frontier:
        nxt = []
        for k in frontier:
            for d in mods.get(k, {}).get("depends_on", []):
                if d not in seen:
                    seen.add(d)
                    order.append(d)
                    nxt.append(d)
        if not transitive:
            break
        frontier = nxt
    return order


def select(index: dict, plan: dict, task_id: str, level: str = "standard") -> dict:
    if level not in LEVELS:
        raise ContextError(f"Уровень контекста: {', '.join(LEVELS)}")
    tasks = {t["id"]: t for t in plan.get("tasks", plan.get("packages", []))}
    t = tasks.get(task_id)
    if not t:
        raise ContextError(f"Задача {task_id} не найдена")
    mods = {m["id"]: m for m in index.get("modules", [])}
    own = task_modules(index, t)
    deps = module_deps(index, own, transitive=(level == "extended"))
    doc_keys: list[str] = []
    for ref in t.get("gdd_refs", []):
        doc_keys.append(ref)
    for mid in own:
        doc_keys += mods[mid].get("docs", [])
    if level == "extended":
        for mid in deps:
            doc_keys += mods[mid].get("docs", [])
    for k in index.get("always_docs", []):
        doc_keys.append(k)
    contracts, interfaces, tests = [], [], []
    for mid in own + deps:  # контракты зависимостей не скрываются ни на каком уровне
        m = mods[mid]
        contracts += m.get("contracts", [])
        interfaces += [f"{mid}: {x}" for x in m.get("public", [])]
    for mid in own:
        tests += mods[mid].get("tests", [])
    return {
        "task": t,
        "modules": own,
        "dependency_modules": deps,
        "docs": list(dict.fromkeys(doc_keys)),
        "contracts": list(dict.fromkeys(contracts)),
        "interfaces": list(dict.fromkeys(interfaces)),
        "tests": list(dict.fromkeys(tests)),
        "depends_on_tasks": [(d, tasks[d]["title"], tasks[d].get("status", "")) for d in t.get("depends_on", []) if d in tasks],
        "critical_rules": BASE_CRITICAL_RULES + [r for r in index.get("critical_rules", []) if r not in BASE_CRITICAL_RULES],
    }


def _excerpt(root: Path | None, path: str, anchor: str, limit: int) -> str:
    if not root or limit <= 0:
        return ""
    p = root / path
    if not p.exists():
        return ""
    lines = p.read_text(encoding="utf-8").splitlines()
    start = 0
    if anchor:
        for i, line in enumerate(lines):
            if line.lstrip("#").strip().lower().startswith(anchor.lower().replace("-", " ")):
                start = i + 1
                break
    body = []
    for line in lines[start:]:
        if anchor and line.startswith("#") and body:
            break
        if line.startswith("#") or line.startswith(">"):
            continue
        if line.strip():
            body.append(line.strip())
        if sum(len(x) for x in body) >= limit:
            break
    text = " ".join(body)
    return (text[:limit] + "…") if len(text) > limit else text


def _resolve_doc(index: dict, ref: str) -> tuple[str, str, str, str]:
    """ref -> (ключ, путь, якорь, заголовок)."""
    key, _, anchor = ref.partition("#")
    d = index.get("docs", {}).get(key)
    if d:
        return key, d["path"], anchor, d.get("title", key)
    return key, key, anchor, key


def pack(index: dict, plan: dict, task_id: str, level: str = "standard", root: Path | None = None) -> str:
    sel = select(index, plan, task_id, level)
    t = sel["task"]
    lim = EXCERPT_CHARS[level]
    out = [f"# Задача {t['id']}: {t['title']}  ·  контекст: {level}",
           f"Проект: {plan.get('project', '')}. Ветка: `{t.get('branch') or 'task/' + t['id'].lower()}` от `{plan.get('default_branch', 'main')}`. PR с `[{t['id']}]` в названии.",
           "", "## Цель", t.get("goal") or t["title"]]
    if level != "brief" and t.get("context"):
        out += ["", "## Контекст", t["context"]]
    out += ["", "## Порядок чтения (экономия токенов)",
            f"1. `{PROJECT_INDEX}` — карта репозитория (не читай весь репозиторий).",
            "2. Документы и контракты ниже, затем разрешённые файлы.",
            "3. Другие файлы — только если без них задачу не решить; укажи в PR, что и зачем читал.",
            "", "## Документы"]
    for ref in sel["docs"]:
        key, path, anchor, title = _resolve_doc(index, ref)
        line = f"- {title}: `{path}{'#' + anchor if anchor else ''}`"
        ex = _excerpt(root, path, anchor, lim)
        if not ex and lim:
            ex = index.get("docs", {}).get(key, {}).get("summary", "")
        if ex:
            line += f"\n  > {ex}"
        out.append(line)
    if not sel["docs"]:
        out.append("- нет специальных документов")
    out += ["", "## Модули", "- " + (", ".join(sel["modules"]) or "не определены (см. индекс)")]
    if sel["dependency_modules"]:
        out.append("- зависимости: " + ", ".join(sel["dependency_modules"]))
    out += ["", "## Межмодульные контракты (обязательно соблюдать)"]
    out += [f"- `{c}`" for c in sel["contracts"]] or ["- нет"]
    if level != "brief" and sel["interfaces"]:
        out += ["", "## Публичные интерфейсы"] + [f"- {i}" for i in sel["interfaces"]]
    if sel["depends_on_tasks"]:
        out += ["", "## Зависимые задачи"] + [f"- {d} — {title} ({st})" for d, title, st in sel["depends_on_tasks"]]
    out += ["", "## Разрешённые файлы"] + ([f"- `{f}`" for f in t.get("file_scope", [])] or ["- определи минимальный набор и укажи в PR"])
    if sel["tests"]:
        out += ["", "## Тесты модуля"] + [f"- `{x}`" for x in sel["tests"]]
    out += ["", "## Критерии готовности"] + [f"- {c}" for c in t.get("done_when", ["Обязательный CI зелёный", "PR слит"])]
    out += ["", "## Критические правила (не сокращаются)"] + [f"- {r}" for r in sel["critical_rules"]]
    return "\n".join(out) + "\n"


# ---------- индекс проекта

def render_index(index: dict, plan: dict | None = None, root: Path | None = None) -> str:
    out = [f"# {index.get('project') or (plan or {}).get('project', '')} · индекс проекта", "",
           "Компактная карта репозитория. Сгенерировано `python3 tools/context_pack.py index --write`.",
           "Исполнитель читает этот файл первым, затем только документы и файлы своей задачи.", "",
           "## Документы", "", "| Ключ | Файл | О чём |", "|---|---|---|"]
    for k, d in index.get("docs", {}).items():
        out.append(f"| {k} | `{d['path']}` | {d.get('summary', d.get('title', ''))} |")
    out += ["", "## Модули", "", "| Модуль | Каталоги | Документы | Контракты | Тесты | Зависит от |", "|---|---|---|---|---|---|"]
    for m in index.get("modules", []):
        out.append(f"| {m['id']} | {', '.join(f'`{p}`' for p in m.get('paths', []))} | {', '.join(m.get('docs', []))} | "
                   f"{', '.join(f'`{c}`' for c in m.get('contracts', [])) or '—'} | {', '.join(f'`{x}`' for x in m.get('tests', [])) or '—'} | "
                   f"{', '.join(m.get('depends_on', [])) or '—'} |")
    if index.get("critical_rules"):
        out += ["", "## Критические правила"] + [f"- {r}" for r in index["critical_rules"]]
    if root:
        res = check(index, plan, root)
        if res["warnings"]:
            out += ["", "## Устаревшие ссылки"] + [f"- {w}" for w in res["warnings"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="NEXUS Smart Context")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack"); p.add_argument("task"); p.add_argument("--level", default="standard", choices=LEVELS)
    c = sub.add_parser("check"); c.add_argument("--strict", action="store_true", help="устаревшие ссылки считать ошибкой")
    i = sub.add_parser("index"); i.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root)
    try:
        index = load_json(root, INDEX_PATH)
        plan = load_json(root, PLAN_PATH) if (root / PLAN_PATH).exists() else {"tasks": []}
        if a.cmd == "pack":
            print(pack(index, plan, a.task, a.level, root), end="")
        elif a.cmd == "check":
            res = check(index, plan, root)
            for w in res["warnings"]:
                print("ПРЕДУПРЕЖДЕНИЕ:", w)
            for e in res["errors"]:
                print("ОШИБКА:", e, file=sys.stderr)
            if res["errors"] or (a.strict and res["warnings"]):
                return 1
            print(f"OK: модулей {len(index.get('modules', []))}, документов {len(index.get('docs', {}))}, устаревших ссылок {len(res['warnings'])}")
        elif a.cmd == "index":
            text = render_index(index, plan, root)
            if a.write:
                (root / PROJECT_INDEX).parent.mkdir(parents=True, exist_ok=True)
                (root / PROJECT_INDEX).write_text(text, encoding="utf-8")
                print("Записано:", PROJECT_INDEX)
            else:
                print(text, end="")
    except ContextError as e:
        print("ОШИБКА:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
