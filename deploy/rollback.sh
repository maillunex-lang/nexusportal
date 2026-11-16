#!/usr/bin/env bash
# Откат NEXUS PORTAL на предыдущую установленную версию.
#   sudo ./deploy/rollback.sh                 # на предыдущую версию кода
#   sudo ./deploy/rollback.sh <версия>        # на конкретную версию из /opt/nexus-portal/releases
#   sudo ./deploy/rollback.sh --db <файл>     # дополнительно восстановить БД из резервной копии
set -euo pipefail
PREFIX=/opt/nexus-portal
DATA=/var/lib/nexus-portal
TARGET=""
DB_BACKUP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB_BACKUP="$2"; shift 2 ;;
    *) TARGET="$1"; shift ;;
  esac
done
[ "$(id -u)" = 0 ] || { echo "Запустите от root" >&2; exit 1; }
CUR="$(readlink "$PREFIX/current")"
if [ -z "$TARGET" ]; then
  TARGET="$(cat "$PREFIX/previous" 2>/dev/null || true)"
  [ -n "$TARGET" ] || TARGET="$(ls -1dt "$PREFIX"/releases/* | grep -v -x -F "$CUR" | head -n 1)"
else
  TARGET="$PREFIX/releases/$TARGET"
fi
[ -d "$TARGET" ] || { echo "Версия для отката не найдена: $TARGET" >&2; exit 2; }
echo "Откат: $CUR -> $TARGET"
systemctl stop nexus-portal.service
if [ -n "$DB_BACKUP" ]; then
  "$TARGET/venv/bin/python" -c "import sys; sys.path.insert(0, '$TARGET'); from backend.core.db import verify_backup; from pathlib import Path; verify_backup(Path('$DB_BACKUP'))"
  cp -a "$DATA/nexus.sqlite3" "$DATA/backups/before-rollback-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
  rm -f -- "$DATA/nexus.sqlite3-wal" "$DATA/nexus.sqlite3-shm"
  install -o nexus -g nexus -m 0640 "$DB_BACKUP" "$DATA/nexus.sqlite3"
  echo "БД восстановлена из $DB_BACKUP"
fi
ln -sfn "$TARGET" "$PREFIX/current.new" && mv -T "$PREFIX/current.new" "$PREFIX/current"
echo "$CUR" > "$PREFIX/previous"
systemctl start nexus-portal.service
sleep 2
systemctl is-active --quiet nexus-portal.service && echo "Откат выполнен" || { echo "Служба не запустилась: journalctl -u nexus-portal" >&2; exit 3; }
