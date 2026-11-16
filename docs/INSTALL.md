# NEXUS PORTAL · установка, настройка и откат

Портал устанавливается на один VPS рядом с другими службами и **не изменяет их**:
слушает только `127.0.0.1:8787`, работает от пользователя `nexus`, пишет только в
`/opt/nexus-portal`, `/var/lib/nexus-portal`, `/etc/nexus-portal` и `/srv/nexus`.
nginx, firewall и чужие службы установщик не трогает.

## 1. Требования

- Linux с systemd, Python 3.12+, пакет `python3-venv`, `curl`, `git`.
- Node.js 20+ — только для сборки интерфейса (можно собрать на другой машине и скопировать `frontend/dist`).
- HTTPS-прокси (nginx/Caddy) перед порталом — cookie сессии имеет флаг `Secure`.

## 2. Установка

```bash
git clone https://github.com/maillunex-lang/nexusportal.git /root/nexusportal-src
cd /root/nexusportal-src
sudo ./deploy/install.sh --check     # только проверки, ничего не меняет
sudo ./deploy/install.sh             # установка
```

Установщик:
1. проверяет Python, systemd и свободный порт (другой порт: `NEXUS_PORT=8790 sudo -E ./deploy/install.sh`);
2. делает проверенную резервную копию БД (при обновлении);
3. ставит код в `/opt/nexus-portal/releases/<git-sha>` с собственным venv, применяет миграции;
4. атомарно переключает `/opt/nexus-portal/current`, перезапускает `nexus-portal.service`;
5. если `/api/health` не ответил за 20 секунд — **автоматически возвращает предыдущую версию**;
6. включает ежедневный `nexus-portal-backup.timer` (14 последних копий в `/var/lib/nexus-portal/backups`).

Создайте владельца (пароль от 12 символов, вводится скрыто):

```bash
cd /opt/nexus-portal/current
sudo -u nexus env $(cat /etc/nexus-portal/nexus-portal.env | xargs) ./venv/bin/python -m backend.cli set-owner admin
```

Подключите HTTPS-прокси по примеру `deploy/nginx-nexus-portal.conf.example` (`nginx -t` перед перезагрузкой).

## 3. Секреты

Секреты хранятся **только** в файлах `/etc/nexus-portal/secrets/*` с правами `0600` (портал отказывается
читать файл с более широкими правами). В браузер, БД, журналы и GitHub они не попадают.
Задать можно в интерфейсе («Настройки → Секреты», значение только записывается) или командой:

```bash
cd /opt/nexus-portal/current
sudo -u nexus env $(cat /etc/nexus-portal/nexus-portal.env | xargs) ./venv/bin/python -m backend.cli set-secret github_token
```

| Имя | Назначение |
|---|---|
| `github_token` | общий fine-grained токен GitHub для всех разрешённых репозиториев |
| `github_webhook_secret` | секрет подписи webhooks (случайная строка ≥ 32 символов: `openssl rand -hex 32`) |
| `telegram_bot_token` | токен Telegram-бота (необязательно) |
| `max_bot_token` | токен бота MAX (необязательно) |

## 4. GitHub

1. Создайте **fine-grained personal access token** (Settings → Developer settings), доступ — только к нужным
   репозиториям. Права: *Contents* read/write, *Pull requests* read/write, *Actions* read,
   *Checks* read, *Commit statuses* read, *Metadata* read, *Administration* read (чтение защиты веток);
   для создания новых репозиториев мастером — *Administration* write.
2. Сохраните токен как секрет `github_token`. В «Настройки → GitHub» укажите список разрешённых репозиториев.
3. В каждом репозитории: Settings → Webhooks → Add webhook
   - Payload URL: `https://<портал>/api/github/webhook`
   - Content type: `application/json`, Secret: значение `github_webhook_secret`
   - События: *Pull requests, Check suites, Check runs, Statuses, Workflow runs, Pushes*.
4. В карточке проекта задайте **обязательные проверки CI** (или включите защиту ветки с required checks) —
   без них автослияние не выполняется. Включите «Автослияние PR».
5. Потерянные webhook подхватывает резервная сверка раз в `NEXUS_SYNC_INTERVAL_MINUTES` (по умолчанию 15 минут)
   и кнопка «Синхронизировать сейчас».

## 5. SSH и деплой проектов

Два режима исполнителя (Настройки → SSH):

- **local** — портал на том же VPS, команды выполняются от пользователя `nexus` локально (рекомендуется для одного VPS);
- **ssh** — прямой SSH к VPS по ключу.

Для SSH:

```bash
sudo -u nexus ssh-keygen -t ed25519 -N '' -f /etc/nexus-portal/secrets/id_ed25519
ssh-keyscan -t ed25519 <хост> | sudo tee /etc/nexus-portal/known_hosts
# публичный ключ /etc/nexus-portal/secrets/id_ed25519.pub добавьте в ~/.ssh/authorized_keys пользователя деплоя
```

Проверка ключа хоста обязательна (`StrictHostKeyChecking=yes`), пароли не используются.
Перезапуск служб проектов — только `nexus-<slug>-*.service`; пример sudoers: `deploy/sudoers-nexus.example`.

Сценарии деплоя задаются **в портале** для каждого проекта и окружения (dev/prod), версионируются
(номер + sha256) и никогда не берутся из PR. Перед каждым деплоем делается архив `shared/` и текущего релиза,
переключение `current` атомарное, при ошибке после переключения — автоматический откат.
Продакшен-деплой разрешается отдельным переключателем в карточке проекта.

## 6. Релизы и APK

1. В проекте задайте имя релизного workflow и артефакта («Релизы → Настройки релизов»), включите автопубликацию.
2. Релизный workflow должен загружать артефакт с `release.json`, `SHA256SUMS` и файлом сборки
   (пример: `templates/release-android.yml`). APK подписывается ключом из секретов GitHub Actions.
3. После успешного релизного CI портал проверяет: событие push/release из основной ветки или тега, не форк,
   SHA запуска = актуальный SHA ветки, канал `release`, контрольная сумма, подпись APK (не debug),
   затем атомарно публикует в `/srv/nexus/<slug>/downloads/<версия>/` и переключает `latest`.
   Хранятся 5 последних версий для отката.
4. Публичные ссылки: задайте `NEXUS_PUBLIC_DOWNLOAD_BASE` и раздачу по примеру nginx.

## 7. Telegram и MAX

- **Telegram:** создайте бота у @BotFather, сохраните токен как `telegram_bot_token`, напишите боту,
  узнайте `chat_id` (например, через `https://api.telegram.org/bot<токен>/getUpdates`), укажите его в «Настройки → Уведомления».
- **MAX:** создайте бота в MAX для бизнеса (платформа MAX), сохраните токен как `max_bot_token`, укажите `chat_id`.
  Портал отправляет `POST https://platform-api.max.ru/messages?chat_id=<id>` с заголовком `Authorization: <токен>`;
  базовый адрес меняется переменной `NEXUS_MAX_API`.
- Включите каналы и нажмите «Отправить тестовое уведомление».

## 8. Обновление

```bash
cd /root/nexusportal-src && git pull && sudo ./deploy/install.sh
```

## 9. Откат

```bash
sudo ./deploy/rollback.sh                       # предыдущая версия кода
sudo ./deploy/rollback.sh <git-sha>             # конкретная версия из /opt/nexus-portal/releases
sudo ./deploy/rollback.sh --db /var/lib/nexus-portal/backups/nexus-<дата>.sqlite3   # + восстановить БД
```

Перед восстановлением БД копия проверяется `PRAGMA integrity_check`, текущая БД сохраняется рядом.

## 10. Аварийная остановка

«Настройки → Аварийный выключатель» останавливает автослияние, автопубликацию и автоматические деплои
всех проектов. Для одного проекта — переключатель «Автоматизация проекта». Полная остановка:
`sudo systemctl stop nexus-portal`.
