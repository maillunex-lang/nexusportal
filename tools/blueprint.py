#!/usr/bin/env python3
"""Обёртка над backend/blueprint/core.py (NEXUS Project Blueprint).

Команды: validate <файл>, order <файл>, next <файл> [--done ...] [--active ...], prompt <файл> <ID> [--executor ...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.blueprint.core import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
