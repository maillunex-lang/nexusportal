# NEXUS PORTAL · индекс проекта

Компактная карта репозитория. Сгенерировано `python3 tools/context_pack.py index --write`.
Исполнитель читает этот файл первым, затем только документы и файлы своей задачи.

## Документы

| Ключ | Файл | О чём |
|---|---|---|
| spec | `docs/GDD.md` | решения владельца и архитектура |
| arch | `docs/ARCHITECTURE.md` | модули, принятые решения, безопасность критических операций |
| protocol | `docs/PORTAL_PROTOCOL.md` | жизненный цикл задачи, автослияние, релизы |
| install | `docs/INSTALL.md` | VPS, секреты, GitHub, SSH, Telegram/MAX |
| rules | `docs/AI_RULES.md` | обязательные правила исполнителей |

## Модули

| Модуль | Каталоги | Документы | Контракты | Тесты | Зависит от |
|---|---|---|---|---|---|
| core | `backend/core/**`, `backend/migrations/**`, `backend/api/**`, `backend/main.py`, `backend/cli.py` | arch, spec | `docs/ARCHITECTURE.md` | `backend/tests/test_core.py` | — |
| ui | `frontend/**` | spec | `docs/ARCHITECTURE.md` | — | core |
| projects | `backend/projects/**` | spec | `docs/ARCHITECTURE.md` | `backend/tests/test_wizard.py` | core, github, prompts, roadmap |
| prompts | `backend/prompts/**` | spec, protocol | `docs/ARCHITECTURE.md` | `backend/tests/test_wizard.py` | roadmap, context |
| roadmap | `backend/roadmap/**`, `tools/work_plan.py` | protocol | `docs/ARCHITECTURE.md` | `backend/tests/test_roadmap.py` | — |
| context | `backend/context/**`, `tools/context_pack.py` | protocol | `docs/ARCHITECTURE.md` | `backend/tests/test_context.py` | — |
| github | `backend/github/**` | spec, install | `docs/ARCHITECTURE.md` | `backend/tests/test_github.py` | core |
| orchestration | `backend/orchestration/**` | protocol, spec | `docs/ARCHITECTURE.md` | `backend/tests/test_automerge.py` | github, roadmap, memory |
| deploy | `backend/deploy/**`, `deploy/**` | install, arch | `docs/ARCHITECTURE.md` | `backend/tests/test_deploy.py` | core, memory |
| releases | `backend/releases/**`, `templates/**` | protocol, install | `docs/ARCHITECTURE.md` | `backend/tests/test_releases.py` | deploy, github |
| memory | `backend/memory/**`, `backend/notifications/**` | spec | `docs/ARCHITECTURE.md` | `backend/tests/test_memory_notify.py` | core |

## Критические правила
- Токены и ключи только в файлах 0600 на сервере; браузеру и логам не отдаются.
- Слияние только после обязательного CI на актуальном SHA; done только после подтверждённого слияния.
- Команды деплоя из PR не выполняются; продакшен — только с разрешения владельца.
