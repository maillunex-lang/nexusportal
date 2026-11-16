#!/usr/bin/env python3
"""Детерминированный план NEXUS PORTAL. Не вызывает AI API."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "docs" / "work_plan.json"

def load():
    return json.loads(PATH.read_text(encoding="utf-8"))

def check(data):
    items = data["packages"]
    ids = [p["id"] for p in items]
    if len(ids) != len(set(ids)):
        raise ValueError("Повторяющиеся ID")
    by_id = {p["id"]: p for p in items}
    for p in items:
        if p["status"] not in {"planned", "ready", "in_progress", "blocked", "done"}:
            raise ValueError("Неизвестный статус")
        for d in p["depends_on"]:
            if d not in by_id:
                raise ValueError("Отсутствует зависимость " + d)
    visiting, visited = set(), set()
    def walk(k):
        if k in visiting:
            raise ValueError("Цикл зависимостей")
        if k in visited:
            return
        visiting.add(k)
        for dep in by_id[k]["depends_on"]:
            walk(dep)
        visiting.remove(k)
        visited.add(k)
    for k in ids:
        walk(k)
    return True

def ready(data):
    by_id = {p["id"]: p for p in data["packages"]}
    return [p for p in data["packages"] if p["status"] in ("planned", "ready")
            and all(by_id[d]["status"] == "done" for d in p["depends_on"])]

def prompt(data, task_id):
    p = next((x for x in data["packages"] if x["id"] == task_id), None)
    if not p:
        raise ValueError("Задача не найдена")
    return (f"Проект: {data['project']}\\nЗадача {p['id']}: {p['title']}\\n"
            f"Прочитай docs/GDD.md и docs/AI_RULES.md. Работай в отдельной ветке, "
            f"открой PR. Не меняй чужие сервисы и не сохраняй секреты. "
            f"Критерии: {', '.join(p['done_when'])}. "
            f"Зависимости: {', '.join(p['depends_on']) or 'нет'}. "
            f"Зелёный CI обязателен, скриншоты не требуются.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["check", "next", "prompt", "set", "render"])
    parser.add_argument("task", nargs="?")
    parser.add_argument("status", nargs="?")
    args = parser.parse_args()
    data = load()
    check(data)
    if args.action == "check":
        print("OK")
    elif args.action == "next":
        for p in ready(data):
            print(p["id"], p["title"])
    elif args.action == "prompt":
        print(prompt(data, args.task))
    elif args.action == "set":
        if args.status not in {"planned", "ready", "in_progress", "blocked", "done"}:
            parser.error("Некорректный статус")
        p = next((x for x in data["packages"] if x["id"] == args.task), None)
        if p is None:
            parser.error("Задача не найдена")
        if args.status == "done":
            parser.error("done разрешено только после подтверждённого merge через портал")
        p["status"] = args.status
        PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    elif args.action == "render":
        print("\\n".join(f"- {p['id']} {p['title']}: {p['status']}" for p in data["packages"]))

if __name__ == "__main__":
    main()
