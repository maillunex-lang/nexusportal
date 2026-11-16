#!/usr/bin/env python3
"""Обёртка над backend/context/engine.py (NEXUS Smart Context) для репозитория NEXUS PORTAL.

В проектах, созданных порталом, этот файл — самодостаточная копия движка.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.context.engine import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
