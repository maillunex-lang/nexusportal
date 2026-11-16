#!/usr/bin/env bash
# Безопасная установка/обновление NEXUS PORTAL на VPS.
#
# Запуск (от root) из корня клонированного репозитория:
#   sudo ./deploy/install.sh            # установка или обновление
#   sudo ./deploy/install.sh --check    # только проверки, без изменений
#
# Что делает:
#   - создаёт системного пользователя nexus (без входа по паролю);
#   - кладёт код в /opt/nexus-portal/releases/<версия> и переключает ссылку current атомарно;
#   - данные: /var/lib/nexus-portal, секреты: /etc/nexus-portal/secrets (0700, файлы 0600);
#   - каталог проектов: /srv/nexus (только для проектов портала);
#   - устанавливает службы nexus-portal.service и nexus-portal-backup.timer.
# Чего НЕ делает: не меняет nginx, firewall, другие службы и проекты; не открывает порты наружу
# (портал слушает 127.0.0.1:8787); не хранит секреты в репозитории.
set -euo pipefail

APP=nexus-portal
PREFIX=/opt/nexus-portal
DATA=/var/lib/nexus-portal
ETC=/etc/nexus-portal
SRV=/srv/nexus
PORT="${NEXUS_PORT:-8787}"
KEEP=3
SRC="$(cd "$(dirname "$0")/.." && pwd)"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

say() { printf '\033[1;32m[nexus]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[nexus] ОШИБКА:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "Запустите от root (sudo)"
command -v python3 >/dev/null || die "Нужен python3 (3.12+)"
python3 - <<'PY' || die "Нужен Python 3.12 или новее"
import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)
PY
command -v systemctl >/dev/null || die "Нужен systemd"
python3 -c "import venv" 2>/dev/null || die "Нужен пакет python3-venv"

if ss -ltn 2>/dev/null | awk '{print $4}' | grep -q ":${PORT}\$"; then
  if ! systemctl is-active --quiet "$APP"; then
    die "Порт ${PORT} занят другой службой. Укажите другой: NEXUS_PORT=8790 ./deploy/install.sh"
  fi
fi

VERSION="$(git -C "$SRC" rev-parse --short=12 HEAD 2>/dev/null || date -u +%Y%m%d%H%M%S)"
say "Версия: $VERSION; источник: $SRC; порт: 127.0.0.1:$PORT"
if [ "$CHECK_ONLY" = 1 ]; then say "Проверки пройдены, изменения не вносились."; exit 0; fi

id nexus >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin nexus
install -d -o root -g root -m 0755 "$PREFIX" "$PREFIX/releases"
install -d -o nexus -g nexus -m 0750 "$DATA" "$DATA/backups"
install -d -o root -g nexus -m 0750 "$ETC"
install -d -o nexus -g nexus -m 0700 "$ETC/secrets"
install -d -o nexus -g nexus -m 0755 "$SRV"

# Предварительная резервная копия БД перед обновлением
if [ -f "$DATA/nexus.sqlite3" ] && [ -x "$PREFIX/current/venv/bin/python" ]; then
  say "Резервная копия БД перед обновлением"
  (cd "$PREFIX/current" && sudo -u nexus env $(grep -v '^#' "$ETC/nexus-portal.env" | xargs) \
    "$PREFIX/current/venv/bin/python" -m backend.cli backup --dir "$DATA/backups") || die "Не удалось сделать резервную копию — обновление остановлено"
fi

REL="$PREFIX/releases/$VERSION"
if [ -e "$REL" ]; then
  say "Релиз $VERSION уже установлен — переустановка"
  rm -r -- "${PREFIX:?}/releases/${VERSION:?}"
fi
TMP="$REL.tmp"
install -d "$TMP"
cp -a "$SRC/backend" "$SRC/tools" "$SRC/docs" "$TMP/"
if [ -d "$SRC/frontend/dist" ]; then
  install -d "$TMP/frontend" && cp -a "$SRC/frontend/dist" "$TMP/frontend/dist"
elif command -v npm >/dev/null; then
  say "Сборка интерфейса"
  (cd "$SRC/frontend" && npm ci --no-audit --no-fund && npm run build)
  install -d "$TMP/frontend" && cp -a "$SRC/frontend/dist" "$TMP/frontend/dist"
else
  die "Нет frontend/dist и npm. Соберите интерфейс: cd frontend && npm ci && npm run build"
fi
python3 -m venv "$TMP/venv"
"$TMP/venv/bin/pip" install --quiet --upgrade pip
"$TMP/venv/bin/pip" install --quiet -r "$SRC/backend/requirements.txt"
find "$TMP" -name '__pycache__' -prune -exec rm -r -- {} +
mv -T "$TMP" "$REL"

if [ ! -f "$ETC/nexus-portal.env" ]; then
  sed "s/__PORT__/$PORT/" "$SRC/deploy/nexus-portal.env.example" > "$ETC/nexus-portal.env"
  chown root:nexus "$ETC/nexus-portal.env"; chmod 0640 "$ETC/nexus-portal.env"
  say "Создан $ETC/nexus-portal.env — проверьте значения"
fi

say "Миграции БД"
sudo -u nexus env $(grep -v '^#' "$ETC/nexus-portal.env" | xargs) "$REL/venv/bin/python" -c \
  "import sys; sys.path.insert(0, '$REL'); from backend.cli import main; sys.exit(main(['migrate']))"

PREV="$(readlink "$PREFIX/current" 2>/dev/null || true)"
ln -sfn "$REL" "$PREFIX/current.new" && mv -T "$PREFIX/current.new" "$PREFIX/current"
echo "$PREV" > "$PREFIX/previous"

sed "s/__PORT__/$PORT/" "$SRC/deploy/nexus-portal.service" > /etc/systemd/system/nexus-portal.service
cp "$SRC/deploy/nexus-portal-backup.service" "$SRC/deploy/nexus-portal-backup.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now nexus-portal-backup.timer >/dev/null
systemctl enable nexus-portal.service >/dev/null
systemctl restart nexus-portal.service

for i in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then OK=1; break; fi
  sleep 1
done
if [ "${OK:-0}" != 1 ]; then
  say "Портал не ответил — автоматический откат"
  if [ -n "$PREV" ]; then
    ln -sfn "$PREV" "$PREFIX/current.new" && mv -T "$PREFIX/current.new" "$PREFIX/current"
    systemctl restart nexus-portal.service
  fi
  die "Новая версия не запустилась. Журнал: journalctl -u nexus-portal -n 100"
fi

# Хранить только последние релизы
ls -1t "$PREFIX/releases" | grep -v -x -F "$VERSION" | tail -n +"$KEEP" | while read -r old; do
  if [ -n "$old" ] && [ "$PREFIX/releases/$old" != "$PREV" ]; then rm -r -- "${PREFIX:?}/releases/${old:?}"; fi
done || true

say "Готово: NEXUS PORTAL $VERSION работает на 127.0.0.1:$PORT"
if ! sudo -u nexus env $(grep -v '^#' "$ETC/nexus-portal.env" | xargs) "$REL/venv/bin/python" -c \
  "import sys; sys.path.insert(0, '$REL'); from backend.core.config import load_settings; from backend.core.db import Database; from backend.core.security import Auth; s=load_settings(); sys.exit(0 if Auth(Database(s.db_path)).owner_exists() else 1)"; then
  say "Создайте владельца: sudo -u nexus env \$(cat $ETC/nexus-portal.env | xargs) $PREFIX/current/venv/bin/python -m backend.cli set-owner <логин>  (из каталога $PREFIX/current)"
fi
say "Дальше: настройте HTTPS-прокси (пример deploy/nginx-nexus-portal.conf.example) и секреты (docs/INSTALL.md)."
