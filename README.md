# NEXUS PORTAL 1.0

Self-hosted система управления разработкой программных проектов (игры, Android-приложения, сайты, серверы и
другое) **без платных ИИ API**. ChatGPT, Claude и Codex работают как внешние директор и исполнители по
копируемым промптам; портал выполняет детерминированную автоматизацию.

Возможности:
- мастер создания/подключения проекта с анализом репозитория и записью **только отсутствующих** файлов (ветка + PR);
- обучающий промпт ИИ-директора, AI_RULES, DIRECTOR_HANDOVER, PORTAL_PROTOCOL, GDD, правила исполнителей;
- дорожная карта `work_plan.json` (DAG, этапы, параллельные линии, готовые задачи, промпты задач);
- GitHub: подписанные webhooks, резервная сверка, PR, коммиты, обязательные проверки на актуальном SHA;
- автослияние после зелёного обязательного CI, `done` только после подтверждённого слияния, промпт исправления при ошибке;
- деплой на один VPS (SSH или локально): dev/prod-сценарии проекта, резервные копии, атомарная замена, откат;
- релизы и APK: проверка артефакта, SHA-256, подписи и SHA, автопубликация, история версий, откат;
- изолированная память проекта, кнопка «Контекст для ИИ», уведомления в портале, Telegram и MAX;
- PWA Forest Glass 2.0 на русском: светлая/тёмная темы, от 360 px, Android safe-area.

## Структура

| Путь | Содержимое |
|---|---|
| `backend/` | FastAPI, SQLite WAL, миграции, модули N1–N10, тесты |
| `frontend/` | React + TypeScript + Vite PWA |
| `deploy/` | установщик, откат, systemd, пример nginx |
| `templates/` | примеры релизных workflow для проектов |
| `tools/work_plan.py` | CLI дорожной карты: `check`, `next`, `lanes`, `prompt <ID>`, `render [--write]` |
| `docs/` | спецификация, план, установка, архитектура, правила |

## Быстрый старт (разработка)

```bash
pip install -r backend/requirements-dev.txt
python -m pytest backend/tests
(cd frontend && npm ci && npm run build)
export NEXUS_DATA_DIR=./var NEXUS_COOKIE_SECURE=0
python -m backend.cli set-owner admin
python -m uvicorn backend.main:app --port 8787    # http://127.0.0.1:8787
```

Установка на VPS, настройка GitHub/SSH/Telegram/MAX и откат: **[docs/INSTALL.md](docs/INSTALL.md)**.
Архитектура и принятые решения: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Спецификация: [docs/GDD.md](docs/GDD.md).
