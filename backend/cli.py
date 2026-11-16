"""Административные команды: python -m backend.cli <команда>"""
from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path

from .core.config import SECRET_NAMES, load_settings
from .core.db import Database, verify_backup
from .core.security import Auth


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nexus")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="Применить миграции")
    o = sub.add_parser("set-owner", help="Создать/сменить владельца")
    o.add_argument("username")
    s = sub.add_parser("set-secret", help="Записать секрет в файл 0600 (значение читается из stdin)")
    s.add_argument("name", choices=SECRET_NAMES)
    b = sub.add_parser("backup", help="Резервная копия БД с проверкой")
    b.add_argument("--dir", default=None)
    v = sub.add_parser("verify-backup", help="Проверить резервную копию")
    v.add_argument("path")
    sub.add_parser("check", help="Проверка конфигурации")
    args = ap.parse_args(argv)
    st = load_settings()
    db = Database(st.db_path)
    if args.cmd == "migrate":
        applied = db.migrate()
        print("Применены миграции:", ", ".join(applied) or "нет новых", "| journal_mode =", db.journal_mode())
    elif args.cmd == "set-owner":
        db.migrate()
        pw = getpass.getpass("Пароль (не короче 12 символов): ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
        Auth(db).set_owner(args.username, pw)
        print("Владелец сохранён, все сессии сброшены.")
    elif args.cmd == "set-secret":
        value = getpass.getpass("Значение: ") if sys.stdin.isatty() else sys.stdin.read()
        st.write_secret(args.name, value)
        print(f"Секрет {args.name} сохранён в {st.secrets_dir} (0600).")
    elif args.cmd == "backup":
        d = Path(args.dir) if args.dir else st.data_dir / "backups"
        dest = d / f"nexus-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.sqlite3"
        db.backup(dest)
        for old in sorted(d.glob("nexus-*.sqlite3"))[:-14]:
            old.unlink()
        print("Резервная копия создана и проверена:", dest)
    elif args.cmd == "verify-backup":
        verify_backup(Path(args.path))
        print("OK")
    elif args.cmd == "check":
        db.migrate()
        print("БД:", st.db_path, "journal_mode =", db.journal_mode())
        print("Секреты:", {k: ("настроен" if v else "нет") for k, v in st.secret_status().items()})
        print("Владелец:", "есть" if Auth(db).owner_exists() else "НЕТ — выполните set-owner")
    return 0


if __name__ == "__main__":
    sys.exit(main())
