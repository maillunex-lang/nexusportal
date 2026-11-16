#!/usr/bin/env python3
"""Детерминированный движок дорожной карты NEXUS PORTAL (только stdlib).

Этот файл самодостаточен: портал копирует его в проекты как ``tools/work_plan.py``.
Команды: check, next, prompt <ID>, render [--write], set <ID> <статус>, lanes.
Не вызывает никаких ИИ API.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

STATUSES = ("planned", "ready", "in_progress", "blocked", "done")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,31}$")


class PlanError(ValueError):
    pass


def normalize(data: dict) -> dict:
    """Привести план к версии 2 (поддерживает старый формат с ``packages``)."""
    if "tasks" not in data and "packages" in data:
        data = dict(data)
        data["tasks"] = data.pop("packages")
    data.setdefault("version", 2)
    data.setdefault("stages", [])
    data.setdefault("tasks", [])
    for t in data["tasks"]:
        t.setdefault("stage", "")
        t.setdefault("lane", "main")
        t.setdefault("goal", t.get("title", ""))
        t.setdefault("context", "")
        t.setdefault("gdd_refs", [])
        t.setdefault("file_scope", [])
        t.setdefault("depends_on", [])
        t.setdefault("done_when", ["Обязательный CI зелёный", "PR слит"])
        t.setdefault("status", "planned")
        t.setdefault("branch", f"task/{t['id'].lower()}")
    return data


def check(data: dict) -> list[str]:
    """Проверить план. Возвращает топологический порядок или бросает PlanError."""
    data = normalize(data)
    tasks = data["tasks"]
    ids = [t.get("id") for t in tasks]
    for i in ids:
        if not isinstance(i, str) or not ID_RE.match(i):
            raise PlanError(f"Некорректный ID задачи: {i!r}")
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise PlanError("Повторяющиеся ID: " + ", ".join(sorted(dup)))
    stage_ids = {s["id"] for s in data["stages"]}
    by_id = {t["id"]: t for t in tasks}
    for t in tasks:
        if not t.get("title"):
            raise PlanError(f"У задачи {t['id']} нет названия")
        if t["status"] not in STATUSES:
            raise PlanError(f"Неизвестный статус {t['status']!r} у {t['id']}")
        if stage_ids and t["stage"] and t["stage"] not in stage_ids:
            raise PlanError(f"Задача {t['id']} ссылается на неизвестный этап {t['stage']}")
        for d in t["depends_on"]:
            if d not in by_id:
                raise PlanError(f"Задача {t['id']}: отсутствует зависимость {d}")
            if d == t["id"]:
                raise PlanError(f"Задача {t['id']} зависит сама от себя")
        if t["status"] == "done":
            for d in t["depends_on"]:
                if by_id[d]["status"] != "done":
                    raise PlanError(f"Задача {t['id']} done, но зависимость {d} не done")
    order: list[str] = []
    state: dict[str, int] = {}

    def walk(k: str, path: list[str]) -> None:
        s = state.get(k, 0)
        if s == 1:
            cyc = path[path.index(k):] + [k]
            raise PlanError("Цикл зависимостей: " + " -> ".join(cyc))
        if s == 2:
            return
        state[k] = 1
        for dep in by_id[k]["depends_on"]:
            walk(dep, path + [k])
        state[k] = 2
        order.append(k)

    for k in ids:
        walk(k, [])
    return order


def ready(data: dict) -> list[dict]:
    """Задачи, у которых все зависимости done и которые ещё не начаты."""
    data = normalize(data)
    by_id = {t["id"]: t for t in data["tasks"]}
    return [t for t in data["tasks"] if t["status"] in ("planned", "ready")
            and all(by_id[d]["status"] == "done" for d in t["depends_on"])]


def refresh_ready(data: dict) -> list[str]:
    """Перевести planned -> ready для разблокированных задач. Вернуть изменённые ID."""
    changed = []
    for t in ready(data):
        if t["status"] == "planned":
            t["status"] = "ready"
            changed.append(t["id"])
    by_id = {t["id"]: t for t in data["tasks"]}
    for t in data["tasks"]:
        if t["status"] == "ready" and not all(by_id[d]["status"] == "done" for d in t["depends_on"]):
            t["status"] = "planned"
            changed.append(t["id"])
    return changed


def lanes(data: dict) -> dict[str, list[str]]:
    data = normalize(data)
    out: dict[str, list[str]] = {}
    for t in data["tasks"]:
        out.setdefault(t["lane"], []).append(t["id"])
    return out


def _bullets(items, empty="—"):
    return "\n".join(f"- {x}" for x in items) if items else f"- {empty}"


def prompt(data: dict, task_id: str) -> str:
    """Подробный детерминированный промпт для исполнителя."""
    data = normalize(data)
    by_id = {t["id"]: t for t in data["tasks"]}
    t = by_id.get(task_id)
    if not t:
        raise PlanError(f"Задача {task_id} не найдена")
    stage = next((s for s in data["stages"] if s["id"] == t["stage"]), None)
    deps = [f"{d} — {by_id[d]['title']} ({by_id[d]['status']})" for d in t["depends_on"]]
    gdd = data.get("gdd", "docs/GDD.md")
    repo = data.get("repo", "")
    base = data.get("default_branch", "main")
    parallel = [x["id"] for x in ready(data) if x["id"] != t["id"]]
    return f"""Ты — исполнитель задачи в проекте «{data.get('project', '')}».
Репозиторий: {repo or '(указан в README)'}; базовая ветка: {base}.

## Задача {t['id']}: {t['title']}
Этап: {stage['title'] if stage else (t['stage'] or '—')}; линия разработки: {t['lane']}.

### Цель
{t['goal']}

### Контекст
{t['context'] or 'См. GDD и историю задач в docs/DIRECTOR_HANDOVER.md.'}

### Ссылки на GDD
{_bullets([gdd] + list(t['gdd_refs']))}

### Зависимости (уже выполнены)
{_bullets(deps, 'нет')}

### Границы файлов (менять только их)
{_bullets(t['file_scope'], 'определи минимально необходимый набор и укажи его в PR')}

### Ветка и PR
- Создай ветку `{t['branch']}` от актуальной `{base}`.
- Открой один Pull Request в `{base}`; в названии укажи `[{t['id']}]`.
- Не меняй общие файлы (docs/GDD.md, docs/work_plan.json, docs/WORK_PLAN.md) — их меняет только директор.

### Критерии готовности
{_bullets(t['done_when'])}

### Порядок чтения (экономия токенов)
1. docs/PROJECT_INDEX.md — карта репозитория. Не читай весь репозиторий.
2. Только документы GDD из списка выше и разрешённые файлы.
3. Дополнительные файлы — лишь при необходимости; в PR перечисли, что и зачем читал.
Компактный пакет: `python3 tools/context_pack.py pack {t['id']} --level brief|standard|extended`.

### Правила
- Соблюдай docs/AI_RULES.md и межмодульные контракты docs/contracts/.
- Никаких секретов, токенов и паролей в коде, коммитах и PR.
- Не используй платные ИИ API. Не трогай чужие сервисы и другие проекты.
- Добавь автоматические тесты в CI; скриншоты и ручная приёмка не нужны.
- Задача считается выполненной только после зелёного обязательного CI и слияния PR порталом.
- Параллельно могут выполняться: {', '.join(parallel) or 'нет'} — не пересекайся с их файлами.
"""


def render(data: dict) -> str:
    data = normalize(data)
    lines = [f"# {data.get('project', '')} · дорожная карта", "",
             "Сгенерировано командой `python3 tools/work_plan.py render`. Источник истины: docs/work_plan.json.", ""]
    stages = data["stages"] or [{"id": "", "title": "Задачи"}]
    for s in stages:
        items = [t for t in data["tasks"] if (t["stage"] == s["id"]) or (not s["id"] and not t["stage"])]
        if not items:
            continue
        lines += [f"## {s['id'] + ' · ' if s['id'] else ''}{s['title']}", "",
                  "| ID | Задача | Линия | Зависит от | Статус |", "|---|---|---|---|---|"]
        for t in items:
            lines.append(f"| {t['id']} | {t['title']} | {t['lane']} | {', '.join(t['depends_on']) or '—'} | {t['status']} |")
        lines.append("")
    orphan = [t for t in data["tasks"] if data["stages"] and t["stage"] not in {s["id"] for s in data["stages"]}]
    if orphan:
        lines += ["## Без этапа", ""] + [f"- {t['id']} {t['title']}: {t['status']}" for t in orphan] + [""]
    nxt = ready(data)
    lines += ["## Готовы к выдаче", "", _bullets([f"{t['id']} {t['title']}" for t in nxt], "нет"), ""]
    return "\n".join(lines)


def set_status(data: dict, task_id: str, status: str, allow_done: bool = False) -> None:
    data = normalize(data)
    if status not in STATUSES:
        raise PlanError(f"Некорректный статус: {status}")
    if status == "done" and not allow_done:
        raise PlanError("done разрешено только после подтверждённого слияния через портал")
    t = next((x for x in data["tasks"] if x["id"] == task_id), None)
    if t is None:
        raise PlanError(f"Задача {task_id} не найдена")
    t["status"] = status


def load(path: Path) -> dict:
    return normalize(json.loads(path.read_text(encoding="utf-8")))


def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Дорожная карта проекта (work_plan.json)")
    parser.add_argument("--file", default="docs/work_plan.json")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("check")
    sub.add_parser("next")
    sub.add_parser("lanes")
    p = sub.add_parser("prompt"); p.add_argument("task")
    r = sub.add_parser("render"); r.add_argument("--write", nargs="?", const="docs/WORK_PLAN.md")
    s = sub.add_parser("set"); s.add_argument("task"); s.add_argument("status")
    args = parser.parse_args(argv)
    path = Path(args.file)
    try:
        data = load(path)
        order = check(data)
        if args.action == "check":
            print(f"OK: задач {len(order)}, порядок: {' '.join(order)}")
        elif args.action == "next":
            for t in ready(data):
                print(f"{t['id']}\t{t['lane']}\t{t['title']}")
        elif args.action == "lanes":
            for lane, ids in lanes(data).items():
                print(f"{lane}: {' '.join(ids)}")
        elif args.action == "prompt":
            print(prompt(data, args.task))
        elif args.action == "render":
            text = render(data)
            if args.write:
                Path(args.write).write_text(text, encoding="utf-8")
                print(f"Записано: {args.write}")
            else:
                print(text)
        elif args.action == "set":
            set_status(data, args.task, args.status)
            check(data)
            save(path, data)
            print(f"{args.task}: {args.status}")
    except PlanError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
