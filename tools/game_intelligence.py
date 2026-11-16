#!/usr/bin/env python3
"""Offline NEXUS Game Intelligence validation and narrow context packaging."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1] / "docs" / "game_intelligence"


def read_json(relative: str, root: Path = ROOT):
    with (root / relative).open(encoding="utf-8") as file:
        return json.load(file)


def check_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username


def validate(root: Path = ROOT) -> dict:
    genres = read_json("genres.json", root)
    sources = read_json("research/sources.json", root)
    snaps = read_json("research/snapshots_2026_11_16.json", root)
    signals = read_json("research/player_signals.json", root)
    errors = []
    ids = [g.get("id") for g in genres.get("genres", [])]
    if len(ids) != len(set(ids)) or not ids or any(not x for x in ids):
        errors.append("genres: invalid or duplicate ids")
    if any(not g.get("mechanics") or not g.get("label") for g in genres.get("genres", [])):
        errors.append("genres: missing label or mechanics")
    source_map = {}
    for s in sources.get("sources", []):
        sid = s.get("id")
        if not sid or sid in source_map:
            errors.append("sources: blank or duplicate id")
        source_map[sid] = s
        if not check_url(s.get("url", "")):
            errors.append(f"sources: invalid URL for {sid}")
    all_rows = 0
    for chart in snaps.get("snapshots", []):
        sid = chart.get("source_id")
        if sid not in source_map:
            errors.append(f"snapshot: unknown source {sid}")
        elif source_map[sid].get("type") not in ("chart_snapshot", "derived_chart"):
            errors.append(f"snapshot: non-chart source {sid}")
        seen_ranks = set()
        for e in chart.get("entries", []):
            all_rows += 1
            rank = e.get("rank")
            if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1 or rank > 200:
                errors.append(f"snapshot: invalid rank in {sid}")
            if rank in seen_ranks:
                errors.append(f"snapshot: duplicate rank in {sid}")
            seen_ranks.add(rank)
            if not isinstance(e.get("title"), str) or not e["title"].strip():
                errors.append(f"snapshot: empty title in {sid}")
    allowed_sentiments = {"positive", "negative", "mixed", "neutral"}
    allowed_confidences = {"low", "medium", "high"}
    seen_signals = set()
    for signal in signals.get("items", []):
        sid = signal.get("id")
        if not sid or sid in seen_signals:
            errors.append("signals: blank or duplicate id")
        seen_signals.add(sid)
        for field in ("game", "genre_id", "source_url", "published_at", "source_type", "theme", "summary", "counterpoint", "design_hypothesis"):
            if not isinstance(signal.get(field), str) or not signal[field].strip():
                errors.append(f"signals: missing {field} in {sid}")
        if signal.get("genre_id") not in ids:
            errors.append(f"signals: invalid genre in {sid}")
        if signal.get("sentiment") not in allowed_sentiments:
            errors.append(f"signals: invalid sentiment in {sid}")
        if signal.get("confidence") not in allowed_confidences:
            errors.append(f"signals: invalid confidence in {sid}")
        if not check_url(signal.get("source_url", "")):
            errors.append(f"signals: invalid source URL in {sid}")
        if signal.get("source_url") not in {s.get("url") for s in sources.get("sources", [])}:
            errors.append(f"signals: missing provenance source for {sid}")
    blueprints = read_json("genre_blueprints.json", root).get("genre_blueprints", [])
    templates = read_json("mechanic_templates.json", root).get("templates", [])
    blueprint_ids = [b.get("id") for b in blueprints]
    if len(blueprint_ids) != len(set(blueprint_ids)):
        errors.append("blueprints: duplicate genre id")
    for b in blueprints:
        if b.get("id") not in ids or not b.get("core_loop") or not b.get("technical") or not b.get("pitfalls"):
            errors.append(f"blueprints: missing core data or unknown genre {b.get('id')}")
    template_ids = [t.get("id") for t in templates]
    if len(template_ids) != len(set(template_ids)) or any(not t for t in template_ids):
        errors.append("templates: duplicate or missing id")
    for t in templates:
        if not t.get("purpose") or not t.get("contracts") or not t.get("tests"):
            errors.append(f"templates: incomplete data in {t.get('id')}")
        if any(g not in ids for g in t.get("genres", [])):
            errors.append(f"templates: unknown genre in {t.get('id')}")
    editorial = read_json("research/editorial_games.json", root).get("games", [])
    editorial_ids = [g.get("id") for g in editorial]
    if len(editorial_ids) != len(set(editorial_ids)) or any(not x for x in editorial_ids):
        errors.append("editorial: missing or duplicate game id")
    for g in editorial:
        if not g.get("title") or not g.get("platforms") or not g.get("basis"):
            errors.append(f"editorial: missing game metadata for {g.get('id')}")
        if not check_url(g.get("source_url", "")):
            errors.append(f"editorial: invalid source URL for {g.get('id')}")
        if not g.get("genres") or any(tag not in ids for tag in g.get("genres", [])):
            errors.append(f"editorial: unknown genre for {g.get('id')}")
        if g.get("confidence") not in allowed_confidences:
            errors.append(f"editorial: invalid confidence for {g.get('id')}")
        if "pc" in g.get("platforms", []) and len(g["platforms"]) == 1 and g.get("mobile_rank") is not None:
            errors.append(f"editorial: PC-only title cannot have mobile rank {g.get('id')}")
    return {
        "ok": not errors,
        "errors": errors,
        "genre_count": len(ids),
        "source_count": len(source_map),
        "chart_entries": all_rows,
        "player_signals": len(seen_signals),
        "genre_blueprints": len(blueprints),
        "editorial_games": len(editorial),
        "mechanic_templates": len(templates),
        "annual_top100_completed": False,
        "note": "Snapshot observations do not constitute 2026 annual genre top-100 rankings.",
    }


def context(genre_id: str, root: Path = ROOT) -> dict:
    genres = read_json("genres.json", root)["genres"]
    match = next((g for g in genres if g["id"] == genre_id), None)
    if match is None:
        raise ValueError(f"Unknown genre: {genre_id}")
    relevant = [
        {k: item[k] for k in ("id", "game", "theme", "sentiment", "summary", "counterpoint", "design_hypothesis", "confidence", "source_url")}
        for item in read_json("research/player_signals.json", root)["items"]
        if item["genre_id"] == genre_id
    ]
    blueprint = next((b for b in read_json("genre_blueprints.json", root)["genre_blueprints"] if b["id"] == genre_id), None)
    templates = [
        t for t in read_json("mechanic_templates.json", root)["templates"]
        if genre_id in t["genres"]
    ]
    return {
        "genre": match,
        "blueprint": blueprint,
        "mechanic_templates": templates,
        "player_signals": relevant,
        "warnings": [
            "This is curated evidence and deterministic retrieval, not model training.",
            "Player opinions are non-representative unless independently established.",
            "Store category charts are not annual editorial genre rankings.",
        ],
    }


def game_catalog(genre_id: str, root: Path = ROOT) -> dict:
    genre_ids = {g["id"] for g in read_json("genres.json", root)["genres"]}
    if genre_id not in genre_ids:
        raise ValueError(f"Unknown genre: {genre_id}")
    games = [
        g for g in read_json("research/editorial_games.json", root)["games"]
        if genre_id in g["genres"]
    ]
    return {
        "genre_id": genre_id,
        "editorial_references": games,
        "count": len(games),
        "ranking_status": "NOT an official or derived 2026 top-100",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "stats", "context", "games"))
    parser.add_argument("--genre", help="Genre ID, required for context")
    args = parser.parse_args()
    result = validate()
    if args.action == "context":
        if not args.genre:
            parser.error("--genre is required for context")
        if not result["ok"]:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        try:
            result = context(args.genre)
        except ValueError as error:
            parser.error(str(error))
    elif args.action == "games":
        if not args.genre:
            parser.error("--genre is required for games")
        if not result["ok"]:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        try:
            result = game_catalog(args.genre)
        except ValueError as error:
            parser.error(str(error))
    elif args.action == "stats":
        result = {k: v for k, v in result.items() if k != "errors"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (args.action in ("context", "games") or result.get("ok", True)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
