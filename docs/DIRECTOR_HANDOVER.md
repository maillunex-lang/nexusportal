# Передача дел директору
Проект: NEXUS PORTAL, репозиторий maillunex-lang/nexusportal.
Читать: README.md -> docs/GDD.md -> docs/ARCHITECTURE.md -> docs/WORK_PLAN.md -> docs/AI_RULES.md -> docs/PORTAL_PROTOCOL.md -> docs/INSTALL.md.
Цель: N1..N10 без платных AI API, с GitHub Webhooks, PWA, памятью, SSH и APK.

Текущее состояние: все пакеты N1–N10 реализованы одним PR из ветки `feat/nexusportal-full-v1`
(backend, frontend, установщик, тесты по каждому пакету в обязательном CI). Статус задач в
`docs/work_plan.json` — `in_progress`; `done` выставляется после слияния PR.
Решения, принятые при реализации, перечислены в docs/ARCHITECTURE.md (IMP, SC, BP).
Дополнения владельца: NEXUS Smart Context (SC) и NEXUS Project Blueprint (BP, стандарт в docs/blueprint/).

Следующие шаги после слияния: установка на VPS по docs/INSTALL.md, настройка секретов GitHub/Telegram/MAX,
подключение первых проектов мастером. Продакшен-деплой выполняет владелец.
