# NEXUS PORTAL · дорожная карта

Сгенерировано командой `python3 tools/work_plan.py render`. Источник истины: docs/work_plan.json.

## S1 · Фундамент

| ID | Задача | Линия | Зависит от | Статус |
|---|---|---|---|---|
| N1 | Backend и безопасность | core | — | in_progress |

## S2 · Интерфейс и интеграции

| ID | Задача | Линия | Зависит от | Статус |
|---|---|---|---|---|
| N2 | Интерфейс Forest Glass 2.0 (PWA) | ui | N1 | in_progress |
| N3 | Мастер создания проектов | projects | N1 | in_progress |
| N6 | GitHub | github | N1 | in_progress |

## S3 · Промпты и план

| ID | Задача | Линия | Зависит от | Статус |
|---|---|---|---|---|
| N4 | Обучение ИИ и промпты | prompts | N3 | in_progress |
| N5 | Дорожная карта | roadmap | N3 | in_progress |

## S4 · Автоматизация и деплой

| ID | Задача | Линия | Зависит от | Статус |
|---|---|---|---|---|
| N7 | Автоматическое слияние | orchestration | N5, N6 | in_progress |
| N8 | SSH и деплой | deploy | N1, N7 | in_progress |

## S5 · Релизы и память

| ID | Задача | Линия | Зависит от | Статус |
|---|---|---|---|---|
| N9 | APK и релизы | releases | N6, N8 | in_progress |
| N10 | Память и уведомления | memory | N3, N5, N6 | in_progress |

## Готовы к выдаче

- нет
