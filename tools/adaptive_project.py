#!/usr/bin/env python3
"""NEXUS Adaptive Project Engine: deterministic planning, no AI API or network."""
from __future__ import annotations
import argparse
import fnmatch
import hashlib
import json
from pathlib import Path

STATUSES = {"todo", "ready", "in_progress", "pr_open", "tests_passed", "accepted", "blocked"}
DONE = {"accepted"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate(plan):
    errors = []
    tasks = plan.get("tasks", [])
    ids = [t.get("id") for t in tasks]
    if not ids or any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        errors.append("task ids must be nonempty and unique")
    index = {t.get("id"): t for t in tasks}
    for t in tasks:
        tid = t.get("id")
        if t.get("status", "todo") not in STATUSES:
            errors.append(f"{tid}: unknown status")
        if not t.get("title") or not t.get("acceptance") or not isinstance(t.get("acceptance"), list):
            errors.append(f"{tid}: title and acceptance criteria required")
        if not isinstance(t.get("dependencies", []), list) or not isinstance(t.get("file_scopes", []), list):
            errors.append(f"{tid}: dependencies and file scopes must be lists")
            continue
        for dep in t.get("dependencies", []):
            if dep == tid or dep not in index:
                errors.append(f"{tid}: invalid dependency {dep}")
        if any(not isinstance(p, str) or p.startswith("/") or ".." in Path(p).parts for p in t.get("file_scopes", [])):
            errors.append(f"{tid}: invalid file scope")
    seen, active = set(), set()
    def visit(node):
        if node in active:
            errors.append(f"cycle at {node}")
            return
        if node in seen:
            return
        active.add(node)
        for dep in index.get(node, {}).get("dependencies", []):
            if dep in index:
                visit(dep)
        active.remove(node)
        seen.add(node)
    for tid in index:
        visit(tid)
    if not plan.get("repository") or not plan.get("base_branch") or not plan.get("gdd_refs"):
        errors.append("repository, base_branch and gdd_refs are required")
    return errors


def scope_overlap(a, b):
    """Conservative overlap: shared roots or wildcard matches, not a proof of non-conflict."""
    for x in a:
        for y in b:
            if x == y or fnmatch.fnmatch(x, y) or fnmatch.fnmatch(y, x):
                return True
            xp, yp = x.split("/"), y.split("/")
            common = 0
            for left, right in zip(xp, yp):
                if left != right and left not in ("*", "**") and right not in ("*", "**"):
                    break
                common += 1
            if common >= 2 and (len(xp) == common or len(yp) == common or "*" in x or "*" in y):
                return True
    return False


def schedule(plan):
    errors = validate(plan)
    if errors:
        raise ValueError("; ".join(errors))
    index = {t["id"]: t for t in plan["tasks"]}
    eligible = [t for t in plan["tasks"] if t.get("status", "todo") in ("todo", "ready")
                and all(index[d].get("status") in DONE for d in t.get("dependencies", []))]
    active = [t for t in plan["tasks"] if t.get("status") in ("in_progress", "pr_open", "tests_passed")]
    eligible = [t for t in eligible if t.get("file_scopes") and not any(scope_overlap(t["file_scopes"], a.get("file_scopes", [])) for a in active)]
    eligible.sort(key=lambda t: (-int(t.get("priority", 0)), t["id"]))
    batches = []
    while eligible:
        batch, remaining = [], []
        for task in eligible:
            if any(scope_overlap(task.get("file_scopes", []), other.get("file_scopes", [])) for other in batch):
                remaining.append(task)
            else:
                batch.append(task)
        batches.append([t["id"] for t in batch])
        eligible = remaining
    blocked = [{"id": t["id"], "waiting_for": [d for d in t.get("dependencies", []) if index[d].get("status") not in DONE]}
               for t in plan["tasks"] if t.get("status", "todo") in ("todo", "ready")
               and any(index[d].get("status") not in DONE for d in t.get("dependencies", []))]
    return {"parallel_batches": batches, "blocked": blocked, "warning": "File scopes are conservative hints; review shared contracts before parallel execution."}


def prompt(plan, task_id):
    errors = validate(plan)
    if errors:
        raise ValueError("; ".join(errors))
    task = next((t for t in plan["tasks"] if t["id"] == task_id), None)
    if task is None:
        raise ValueError(f"unknown task: {task_id}")
    index = {t["id"]: t for t in plan["tasks"]}
    unmet = [d for d in task.get("dependencies", []) if index[d].get("status") not in DONE]
    if unmet:
        raise ValueError(f"task is blocked by: {', '.join(unmet)}")
    if not task.get("file_scopes"):
        raise ValueError("file scopes must be confirmed before dispatch")
    active = [t for t in plan["tasks"] if t.get("status") in ("in_progress", "pr_open", "tests_passed") and t["id"] != task_id]
    if any(scope_overlap(task["file_scopes"], t.get("file_scopes", [])) for t in active):
        raise ValueError("file scopes conflict with active task")
    if task.get("status", "todo") not in ("todo", "ready"):
        raise ValueError("task is not in a dispatchable status")
    ref = plan.get("base_sha")
    ref_text = f"base SHA {ref}" if ref else "resolve fresh base SHA before starting; never invent a SHA"
    lines = [
        f"Задание {task_id}: {task['title']}",
        f"Репозиторий: {plan['repository']}. Базовая ветка: {plan['base_branch']}; {ref_text}.",
        f"Рабочая ветка: {task.get('branch', 'task/' + task_id.lower())}. Не пушить в main.",
        "GDD и контракты: " + ", ".join(plan["gdd_refs"]),
        "Область изменений: " + (", ".join(task.get("file_scopes", [])) or "НЕ ОПРЕДЕЛЕНА: запросить подтверждение области перед записью"),
        "Зависимости: " + (", ".join(task.get("dependencies", [])) or "нет"),
        "Цель: " + task.get("description", task["title"]),
        "Критерии приёмки:",
        *[f"- {criterion}" for criterion in task["acceptance"]],
        "Проверки: " + (", ".join(task.get("checks", [])) or "определить и документировать безопасные проверки"),
        "Правила: сначала читать GDD и фактическую структуру репозитория; при несовпадении путей не угадывать и не менять чужие зоны; не раскрывать секреты; не удалять данные; создать PR, не сливать автоматически.",
        "Отчёт: изменённые файлы, тесты и результаты, SHA, PR, допущения и оставшиеся риски.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["validate", "next", "prompt"])
    parser.add_argument("plan", type=Path)
    parser.add_argument("--task")
    args = parser.parse_args()
    plan = load(args.plan)
    errors = validate(plan)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    if args.action == "validate":
        print(json.dumps({"ok": True, "tasks": len(plan["tasks"])}, ensure_ascii=False))
    elif args.action == "next":
        print(json.dumps(schedule(plan), ensure_ascii=False, indent=2))
    else:
        if not args.task:
            parser.error("--task required for prompt")
        try:
            print(prompt(plan, args.task))
        except ValueError as error:
            parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
