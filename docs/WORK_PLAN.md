# NEXUS PORTAL · план реализации

| Пакет | Результат | Зависимости |
|---|---|---|
| N1 | Backend, SQLite, auth, API, CI | нет |
| N2 | Forest Glass PWA | N1 API |
| N3 | Мастер GitHub и безопасная запись шаблонов | N1 |
| N4 | Обучающие промпты, правила и handover | N3 |
| N5 | DAG дорожной карты и генератор задач | N3 |
| N6 | GitHub Webhooks, required CI и синхронизация | N1 |
| N7 | Автослияние, статусы done, следующие задачи | N5,N6 |
| N8 | SSH, dev/prod, копии и откат | N1,N7 |
| N9 | APK и публичные релизы после релизного CI | N6,N8 |
| N10 | Память, контекст, Telegram/MAX | N3,N5,N6 |

Исполнители работают в отдельных ветках и PR; shared files docs/GDD.md и docs/WORK_PLAN.md изменяет только директор. Не выдавать статус done до успешного слияния. На каждом этапе тесты включены в CI, не требовать скриншотов. Файловые зоны: N1 backend/**; N2 frontend/**; N3 backend/projects/** templates/**; N4 backend/prompts/**; N5 backend/roadmap/**; N6 backend/github/**; N7 backend/orchestration/**; N8 backend/deploy/**; N9 backend/releases/**; N10 backend/memory/** backend/notifications/**. Пересечения требуют последовательной интеграции.
