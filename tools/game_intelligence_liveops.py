#!/usr/bin/env python3
"""Validate dated live-ops research independently of genre ranking data."""
import argparse
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1] / "docs/game_intelligence"
ALLOWED_KINDS = {"industry_report_observation", "adjacent_genre_reference", "platform_ecosystem_observation"}


def validate_cases(data, genre_ids):
    errors = []
    if data.get("schema_version") != 1:
        errors.append("unsupported schema_version")
    if data.get("status") != "selected_2026_industry_case_studies_not_annual_rankings":
        errors.append("cases must not claim to be annual rankings")
    seen = set()
    for case in data.get("cases", []):
        cid = case.get("id")
        if not isinstance(cid, str) or not cid or cid in seen:
            errors.append("missing or duplicate case id")
        seen.add(cid)
        try:
            period = case["period"]
            if len(period) != 7 or period[4] != "-" or date.fromisoformat(period + "-01").year != 2026:
                raise ValueError()
        except (KeyError, ValueError, TypeError):
            errors.append(f"{cid}: invalid 2026 month")
        url = urlparse(case.get("source_url", ""))
        if url.scheme != "https" or not url.hostname or url.username:
            errors.append(f"{cid}: invalid source URL")
        if case.get("evidence_type") not in ALLOWED_KINDS:
            errors.append(f"{cid}: invalid evidence type")
        ids = case.get("genre_ids", [])
        if not ids or any(g not in genre_ids for g in ids):
            errors.append(f"{cid}: invalid genre IDs")
        for field in ("game", "observed", "design_hypothesis"):
            if not isinstance(case.get(field), str) or not case[field].strip():
                errors.append(f"{cid}: missing {field}")
        for field in ("mechanics", "testable_questions", "limitations"):
            items = case.get(field)
            if not isinstance(items, list) or not items or any(not isinstance(x, str) or not x.strip() for x in items):
                errors.append(f"{cid}: missing {field}")
        if "rank" in case or "annual_top100" in case:
            errors.append(f"{cid}: cannot claim annual rank in case study")
    if not data.get("cases"):
        errors.append("no cases")
    return errors


def report(root=ROOT, genre=None):
    genres = json.loads((root / "genres.json").read_text(encoding="utf-8"))
    data = json.loads((root / "research/live_ops_cases_2026.json").read_text(encoding="utf-8"))
    genre_ids = {g["id"] for g in genres["genres"]}
    errors = validate_cases(data, genre_ids)
    if genre is not None and genre not in genre_ids:
        raise ValueError(f"unknown genre: {genre}")
    cases = [c for c in data["cases"] if genre is None or genre in c["genre_ids"]]
    return {"ok": not errors, "errors": errors, "status": data["status"], "genre": genre, "case_count": len(cases), "cases": cases, "annual_top100_complete": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["validate", "cases"])
    p.add_argument("--genre")
    args = p.parse_args()
    result = report(genre=args.genre)
    if args.command == "validate":
        result.pop("cases")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
