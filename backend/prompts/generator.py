"""Детерминированная генерация обучающих файлов и промптов (без ИИ API).

ChatGPT, Claude и Codex — внешние исполнители: портал только готовит для них тексты.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..projects.analyzer import KINDS, TEMPLATES

ENGINE_PATH = Path(__file__).resolve().parents[1] / "roadmap" / "engine.py"
CONTEXT_ENGINE_PATH = Path(__file__).resolve().parents[1] / "context" / "engine.py"
BLUEPRINT_CORE_PATH = Path(__file__).resolve().parents[1] / "blueprint" / "core.py"

# Тематические документы GDD: ключ -> (файл, заголовок, краткое описание)
GDD_DOCS = {
    "gdd.vision": ("docs/gdd/01_vision.md", "Цель и аудитория", "зачем проект, для кого, платформы"),
    "gdd.features": ("docs/gdd/02_features.md", "Функциональность", "функции и приоритеты"),
    "gdd.architecture": ("docs/gdd/03_architecture.md", "Архитектура и модули", "модули, зоны файлов, данные"),
    "gdd.ui": ("docs/gdd/04_ui.md", "Интерфейс", "экраны, адаптивность, доступность"),
    "gdd.quality": ("docs/gdd/05_quality.md", "Качество и безопасность", "нефункциональные требования, тесты, безопасность"),
    "gdd.release": ("docs/gdd/06_release.md", "Релизы и эксплуатация", "сборка, публикация, откат"),
    "gdd.decisions": ("docs/gdd/DECISIONS_APPROVED.md", "Утверждённые решения", "решения владельца"),
}
LANE_DOCS = {
    "core": ["gdd.architecture"], "gameplay": ["gdd.features"], "ui": ["gdd.ui"], "data": ["gdd.architecture"],
    "api": ["gdd.architecture"], "security": ["gdd.quality"], "release": ["gdd.release"], "feature": ["gdd.features"],
    "director": ["gdd.vision"],
}

KIND_STARTER = {
    "game": [
        ("S1", "Прототип", [
            ("T1", "Каркас проекта и CI", "core", "Создать структуру проекта, сборку и CI-проверки (экспорт/тесты).", ["project.godot", "scenes/**", ".github/workflows/**"]),
            ("T2", "Основная игровая механика", "gameplay", "Реализовать базовый игровой цикл по GDD.", ["scripts/gameplay/**", "scenes/gameplay/**"]),
            ("T3", "Интерфейс меню", "ui", "Главное меню, пауза, настройки звука.", ["scenes/ui/**", "scripts/ui/**"]),
        ]),
        ("S2", "Релиз", [
            ("T4", "Релизная сборка и артефакт", "release", "Workflow релиза с release.json и SHA256SUMS.", [".github/workflows/release.yml", "export_presets.cfg"]),
        ]),
    ],
    "android": [
        ("S1", "Основа", [
            ("T1", "Каркас Gradle и CI", "core", "Модуль app, сборка, unit-тесты в CI.", ["app/**", "build.gradle*", "settings.gradle*", ".github/workflows/**"]),
            ("T2", "Главный экран", "ui", "Главный экран по GDD.", ["app/src/main/java/**/ui/**", "app/src/main/res/**"]),
            ("T3", "Слой данных", "data", "Модели, хранилище, репозитории.", ["app/src/main/java/**/data/**"]),
        ]),
        ("S2", "Релиз", [
            ("T4", "Подписанный релизный APK", "release", "Release workflow: подпись ключом из секретов GitHub, release.json, SHA256SUMS.", [".github/workflows/release.yml"]),
        ]),
    ],
    "web": [
        ("S1", "Основа", [
            ("T1", "Каркас и CI", "core", "Сборка, линтер, тесты в CI.", ["package.json", "src/**", ".github/workflows/**"]),
            ("T2", "Главная страница", "ui", "Вёрстка главной по GDD, адаптив от 360 px.", ["src/pages/**", "src/components/**"]),
            ("T3", "API-клиент", "data", "Работа с данными и обработка ошибок.", ["src/api/**"]),
        ]),
        ("S2", "Публикация", [
            ("T4", "Сборка для VPS", "release", "Статическая сборка как артефакт release.", [".github/workflows/release.yml"]),
        ]),
    ],
    "server": [
        ("S1", "Основа", [
            ("T1", "Каркас сервиса и CI", "core", "Структура, конфигурация, тесты в CI.", ["src/**", "tests/**", ".github/workflows/**"]),
            ("T2", "API и хранилище", "api", "Основные эндпоинты и миграции.", ["src/api/**", "migrations/**"]),
            ("T3", "Безопасность", "security", "Аутентификация, лимиты, журналирование без секретов.", ["src/auth/**"]),
        ]),
        ("S2", "Эксплуатация", [
            ("T4", "Сборка релиза", "release", "Артефакт release для деплоя порталом.", [".github/workflows/release.yml"]),
        ]),
    ],
    "other": [
        ("S1", "Основа", [
            ("T1", "Каркас и CI", "core", "Структура проекта и автоматические проверки.", ["src/**", ".github/workflows/**"]),
            ("T2", "Первая функция", "feature", "Первая функция из GDD.", ["src/**"]),
        ]),
    ],
}


def initial_plan(p: dict) -> dict:
    """Стартовая дорожная карта. Директор уточняет её после утверждения GDD."""
    stages = [{"id": "S0", "title": "Проектирование"}]
    tasks = [{
        "id": "T0", "title": "GDD и дорожная карта", "stage": "S0", "lane": "director",
        "goal": "Директор готовит docs/GDD.md, решения и docs/work_plan.json; владелец утверждает ключевые решения.",
        "gdd_refs": ["gdd.vision", "gdd.decisions"], "file_scope": ["docs/**"], "depends_on": [],
        "done_when": ["GDD утверждён владельцем", "work_plan.json проходит check", "PR слит"],
        "branch": "task/t0-gdd", "status": "planned",
    }]
    for sid, stitle, items in KIND_STARTER[p["kind"]]:
        stages.append({"id": sid, "title": stitle})
        for tid, title, lane, goal, scope in items:
            deps = ["T0"] if tid in ("T1",) else (["T1"] if tid != "T4" else [t[0] for t in KIND_STARTER[p["kind"]][0][2]])
            tasks.append({"id": tid, "title": title, "stage": sid, "lane": lane, "goal": goal,
                          "gdd_refs": LANE_DOCS.get(lane, ["gdd.features"]), "modules": [lane],
                          "file_scope": scope, "depends_on": deps,
                          "done_when": ["Обязательный CI зелёный", "Тесты покрывают новую логику", "PR слит порталом"],
                          "branch": f"task/{tid.lower()}", "status": "planned"})
    return {"project": p["name"], "version": 2, "repo": p.get("repo_full_name") or "",
            "default_branch": p.get("default_branch") or "main", "gdd": "docs/GDD.md",
            "stages": stages, "tasks": tasks}


def readme(p: dict) -> str:
    return f"""# {p['name']}

{p['description'] or 'Описание проекта будет дополнено директором.'}

Тип: {KINDS[p['kind']]}. Шаблон: {TEMPLATES[p['template']]}.

Проект управляется через NEXUS PORTAL: задачи, PR, CI и релизы.

- Спецификация: `docs/GDD.md`
- Дорожная карта: `docs/work_plan.json` (`python3 tools/work_plan.py next`)
- Правила для ИИ: `docs/AI_RULES.md`, `docs/PORTAL_PROTOCOL.md`
"""


def ai_rules(p: dict) -> str:
    return f"""# Правила ИИ · {p['name']}

1. Перед работой прочитай README.md, docs/GDD.md, docs/PORTAL_PROTOCOL.md и свою задачу полностью.
2. Платные ИИ API не используются. ChatGPT, Claude и Codex работают как внешние исполнители по промптам портала.
3. Одна задача — одна ветка — один Pull Request. Ветка указана в промпте задачи.
4. Меняй только файлы из границ задачи. Общие файлы (docs/GDD.md, docs/work_plan.json, docs/WORK_PLAN.md,
   docs/gdd/DECISIONS_APPROVED.md) меняет только директор.
5. Никаких секретов, токенов, паролей и приватных ключей в коде, коммитах, PR и чатах.
6. Каждое изменение сопровождается автоматическими тестами в CI. Скриншоты и ручная повторная приёмка не требуются.
7. Задача выполнена только после зелёного обязательного CI на актуальном SHA и слияния PR порталом.
8. Если CI упал — исправляй в той же ветке по промпту исправления; не ослабляй и не отключай проверки.
9. Не трогай другие сервисы и проекты на сервере. Команды деплоя из PR не выполняются.
10. Релиз публикуется только из релизного workflow (канал release, подписанная сборка, SHA256SUMS).
"""


def portal_protocol(p: dict) -> str:
    return f"""# Протокол NEXUS PORTAL · {p['name']}

## Роли
- **Владелец** — утверждает ключевые решения, включает автоматизацию, разрешает продакшен.
- **ИИ-директор** (внешний ChatGPT/Claude) — ведёт GDD и docs/work_plan.json, выдаёт задачи.
- **Исполнители** (внешние ChatGPT/Claude/Codex) — выполняют задачи в отдельных ветках.
- **Портал** — детерминированная автоматика без ИИ: PR/CI, слияние, релизы, память, уведомления.

## Жизненный цикл задачи
`planned` → `ready` (все зависимости done) → `in_progress` (открыт PR с `[ID]` в названии или веткой задачи)
→ `blocked` (упал CI; портал формирует промпт исправления) → `done` (только после подтверждённого слияния).

## Автоматическое слияние
Портал сливает PR, если: автослияние разрешено для проекта; аварийные выключатели не активны;
PR направлен в `{p.get('default_branch') or 'main'}`, не из форка, привязан к задаче; все обязательные проверки
успешны на актуальном head SHA; конфликтов нет. Слияние выполняется с проверкой SHA.

## Релизы
Релизный workflow публикует артефакт, содержащий `release.json`
(`{{"version":"1.2.3","version_code":10203,"channel":"release","sha":"<SHA>","file":"app-release.apk"}}`),
`SHA256SUMS` и файл сборки. Портал проверяет SHA, контрольную сумму и подпись, затем атомарно публикует версию
и хранит предыдущие для отката.

## Дорожная карта
`python3 tools/work_plan.py check | next | lanes | prompt <ID> | render --write`
"""


def director_handover(p: dict) -> str:
    return f"""# Передача дел директору · {p['name']}

Проект подключён к NEXUS PORTAL. Актуальный промпт передачи дел генерирует кнопка «Контекст для ИИ» в портале —
он всегда содержит текущее состояние задач, PR, ошибок, решений и релизов.

Порядок чтения: README.md → docs/GDD.md → docs/gdd/DECISIONS_APPROVED.md → docs/PORTAL_PROTOCOL.md →
docs/AI_RULES.md → docs/work_plan.json.

Текущее состояние: проект создан мастером. Первая задача T0 — подготовить GDD и дорожную карту.
"""


def executor_rules(p: dict) -> str:
    return f"""# Правила исполнителя · {p['name']}

- Получи промпт задачи из портала (кнопка «Промпт»). В нём цель, контекст, GDD, границы файлов, ветка и критерии.
- Создай ветку из актуальной `{p.get('default_branch') or 'main'}`, открой PR с `[ID задачи]` в названии.
- Добавь тесты, чтобы CI проверял результат. Не отключай существующие проверки.
- Не меняй файлы вне границ задачи и общие файлы директора.
- После зелёного CI портал сам сольёт PR; дополнительных отчётов и скриншотов не нужно.
"""


def gdd(p: dict) -> str:
    """docs/GDD.md — короткое оглавление; содержание разделено на тематические файлы."""
    rows = "\n".join(f"| {k} | [{t}]({path.removeprefix('docs/')}) | {d} |" for k, (path, t, d) in GDD_DOCS.items())
    return f"""# {p['name']} · GDD (оглавление)

GDD разделён на тематические документы. Читай только нужные задаче (они указаны в её пакете контекста).
Общая карта репозитория: docs/PROJECT_INDEX.md.

| Ключ | Документ | О чём |
|---|---|---|
{rows}
"""


def gdd_parts(p: dict) -> dict[str, str]:
    t = "_Заполняет директор._"
    body = {
        "gdd.vision": f"## Цель\n{p.get('goals') or t}\n\n## Аудитория\n{p.get('audience') or t}\n\n## Платформы\n{p.get('platforms') or t}\n",
        "gdd.features": "## Функции\n_Список функций с приоритетами (P0/P1/P2) и ссылками на задачи._\n",
        "gdd.architecture": f"## Технологии\n{p.get('stack') or TEMPLATES[p['template']]}\n\n## Модули\n_Модули и их каталоги ведутся в docs/context/modules.json._\n\n## Контракты\n_Межмодульные интерфейсы — в docs/contracts/._\n",
        "gdd.ui": "## Экраны\n_Экраны и сценарии. Адаптация от 360 px._\n",
        "gdd.quality": "## Требования\nПроизводительность, безопасность, доступность.\n\n## Тесты\nКаждая задача добавляет автоматические тесты в CI.\n",
        "gdd.release": "## Релизы\nРелизная сборка из CI (release.json + SHA256SUMS), публикация порталом, откат.\n",
    }
    return {GDD_DOCS[k][0]: f"# {p['name']} · {GDD_DOCS[k][1]}\n\n{v}" for k, v in body.items()}


def modules_index(p: dict, plan: dict) -> dict:
    """docs/context/modules.json: модули = линии стартового плана."""
    mods = {}
    for t in plan["tasks"]:
        lane = t["lane"]
        if lane == "director":
            continue
        m = mods.setdefault(lane, {"id": lane, "title": lane, "paths": [], "docs": list(LANE_DOCS.get(lane, ["gdd.features"])),
                                   "contracts": [f"docs/contracts/{lane}.md"], "tests": [f"tests/{lane}/**"],
                                   "public": [], "depends_on": []})
        for f in t["file_scope"]:
            if f not in m["paths"]:
                m["paths"].append(f)
    for lane, m in mods.items():
        if lane != "core" and "core" in mods:
            m["depends_on"] = ["core"]
    return {
        "version": 1, "project": p["name"],
        "docs": {k: {"path": path, "title": t, "summary": d} for k, (path, t, d) in GDD_DOCS.items()},
        "always_docs": ["gdd.decisions"],
        "modules": list(mods.values()),
        "critical_rules": ["Релиз публикуется только из релизного workflow (канал release, подпись, SHA256SUMS)."],
    }


def decisions(p: dict) -> str:
    return f"""# Утверждённые решения · {p['name']}

| ID | Решение | Дата | Утвердил |
|---|---|---|---|
| D-01 | Проект управляется через NEXUS PORTAL, без платных ИИ API | — | владелец |
"""


def workflow(p: dict) -> str:
    extra = {
        "godot": "",
        "android": """
  gradle:
    name: nexus-build
    runs-on: ubuntu-latest
    if: hashFiles('gradlew') != ''
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with: {distribution: temurin, java-version: '17'}
      - run: chmod +x gradlew && ./gradlew --no-daemon test
""",
        "web": """
  node:
    name: nexus-build
    runs-on: ubuntu-latest
    if: hashFiles('package.json') != ''
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: {node-version: '20'}
      - run: npm ci && npm run build --if-present && npm test --if-present
""",
        "backend": "",
        "universal": "",
    }[p["template"]]
    return f"""name: nexus-checks
on:
  pull_request:
  push:
    branches: [{p.get('default_branch') or 'main'}]
permissions:
  contents: read
jobs:
  plan:
    name: nexus-plan
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {{python-version: '3.12'}}
      - run: python3 tools/work_plan.py check
      - run: python3 tools/work_plan.py next
      - run: python3 tools/context_pack.py check
{extra}"""


def work_plan_md(plan: dict) -> str:
    from ..roadmap import engine
    return engine.render(plan)


def project_files(p: dict, analysis: dict) -> dict[str, str]:
    plan = initial_plan(p)
    return {
        "README.md": readme(p),
        "docs/AI_RULES.md": ai_rules(p),
        "docs/DIRECTOR_HANDOVER.md": director_handover(p),
        "docs/PORTAL_PROTOCOL.md": portal_protocol(p),
        "docs/EXECUTOR_RULES.md": executor_rules(p),
        "docs/GDD.md": gdd(p),
        **gdd_parts(p),
        "docs/context/modules.json": json.dumps(modules_index(p, plan), ensure_ascii=False, indent=2) + "\n",
        "docs/PROJECT_INDEX.md": project_index(p, plan),
        "tools/context_pack.py": CONTEXT_ENGINE_PATH.read_text(encoding="utf-8"),
        "tools/blueprint.py": BLUEPRINT_CORE_PATH.read_text(encoding="utf-8"),
        "docs/gdd/DECISIONS_APPROVED.md": decisions(p),
        "docs/work_plan.json": json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        "docs/WORK_PLAN.md": work_plan_md(plan),
        "tools/work_plan.py": ENGINE_PATH.read_text(encoding="utf-8"),
        ".github/workflows/nexus-checks.yml": workflow(p),
    }


def project_index(p: dict, plan: dict) -> str:
    from ..context import engine as ctx
    return ctx.render_index(modules_index(p, plan), plan)


def director_bootstrap_prompt(p: dict) -> str:
    """Стартовый обучающий промпт ИИ-директора (копируется в ChatGPT/Claude)."""
    repo = p.get("repo_full_name") or "(репозиторий будет подключён позже)"
    return f"""Ты — ИИ-директор программного проекта «{p['name']}». Работай как ведущий архитектор и руководитель разработки.

## Проект
- Тип: {KINDS[p['kind']]}; шаблон: {TEMPLATES[p['template']]}
- Репозиторий: {repo}; основная ветка: {p.get('default_branch') or 'main'}
- Описание: {p.get('description') or '—'}
- Цели: {p.get('goals') or '—'}
- Аудитория: {p.get('audience') or '—'}
- Платформы: {p.get('platforms') or '—'}
- Технологии: {p.get('stack') or '—'}

## Как устроена работа
Проект подключён к NEXUS PORTAL — детерминированной системе управления без ИИ. Портал:
- хранит дорожную карту (docs/work_plan.json) и выдаёт готовые задачи с подробными промптами;
- отслеживает PR и обязательные проверки CI через GitHub;
- автоматически сливает разрешённые PR после зелёного CI и отмечает задачи выполненными;
- при ошибке CI формирует промпт исправления;
- публикует проверенные релизы и хранит память проекта.
Ты и исполнители (ChatGPT, Claude, Codex) — внешние участники и работаете по копируемым промптам.

## Твоя первая задача (T0)
1. Прочитай README.md, docs/AI_RULES.md, docs/PORTAL_PROTOCOL.md, docs/EXECUTOR_RULES.md.
2. Задай владельцу вопросы, нужные для GDD (по одному блоку), предложи варианты с рекомендацией.
3. Подготовь docs/GDD.md и docs/gdd/DECISIONS_APPROVED.md (только утверждённые владельцем решения).
4. Составь docs/work_plan.json: этапы (stages), задачи (tasks) с полями id, title, stage, lane, goal, context,
   gdd_refs, file_scope, depends_on, done_when, branch. Зависимости — DAG без циклов.
   Раздели работу на параллельные линии (lane) с непересекающимися file_scope.
   GDD держи разделённым на тематические файлы docs/gdd/*.md (оглавление — docs/GDD.md), не один большой документ.
   Для каждой задачи укажи gdd_refs ключами документов (например gdd.features#Функции) и modules.
5. Веди машинный индекс docs/context/modules.json (модули, каталоги, документы, контракты docs/contracts/, тесты,
   зависимости без циклов) и обновляй docs/PROJECT_INDEX.md: `python3 tools/context_pack.py index --write`.
   Проверка: `python3 tools/context_pack.py check`, `python3 tools/work_plan.py check`, затем `render --write`.
6. Открой PR `[T0] GDD и дорожная карта`. После слияния портал откроет следующие задачи.
7. После утверждения GDD и дорожной карты владельцем сформируй NEXUS Project Blueprint — единый JSON
   стандарта `nexus-blueprint/1` со всеми этапами, задачами, зависимостями, приоритетами, критериями и промптами.
   Полная инструкция — промпт ИИ-архитектора в портале (раздел «Blueprint»). Сохрани его как docs/blueprint.json
   и проверь: `python3 tools/blueprint.py validate docs/blueprint.json`.

## Правила
- Не используй платные ИИ API и не проси секреты в чате.
- Общие файлы (GDD, work_plan.json, WORK_PLAN.md, решения) меняешь только ты.
- Каждая задача: отдельная ветка, один PR, тесты в CI, без скриншотов и ручной приёмки.
- Задача выполнена только после зелёного обязательного CI и слияния PR.
- Продакшен-деплой и автопубликацию релизов включает только владелец в портале.
"""
