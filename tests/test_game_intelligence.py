"""Offline tests for Game Intelligence evidence and context contract."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.game_intelligence import ROOT, check_url, context, validate


class GameIntelligenceTests(unittest.TestCase):
    def test_valid_starter_dataset(self):
        result = validate()
        self.assertTrue(result["ok"], result["errors"])

    def test_dataset_counts(self):
        result = validate()
        self.assertEqual(result["genre_count"], 12)
        self.assertEqual(result["chart_entries"], 92)
        self.assertEqual(result["player_signals"], 8)

    def test_not_claiming_annual_top100(self):
        self.assertFalse(validate()["annual_top100_completed"])

    def test_url_guards(self):
        self.assertTrue(check_url("https://example.org/a"))
        self.assertFalse(check_url("http://example.org/a"))
        self.assertFalse(check_url("https://user:pass@example.org/a"))
        self.assertFalse(check_url("https:///relative"))

    def test_targeted_context(self):
        result = context("economic_simulation")
        self.assertEqual(result["genre"]["id"], "economic_simulation")
        self.assertTrue(result["player_signals"])
        self.assertTrue(all(s["theme"] for s in result["player_signals"]))

    def test_context_does_not_load_other_genres(self):
        result = context("mmorpg")
        self.assertEqual(len(result["player_signals"]), 1)
        self.assertEqual(result["player_signals"][0]["game"], "Albion Online")

    def test_unknown_genre_rejected(self):
        with self.assertRaises(ValueError):
            context("unknown")

    def mutate(self, path, fn):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "data"
            shutil.copytree(ROOT, target)
            file = target / path
            data = json.loads(file.read_text(encoding="utf-8"))
            fn(data)
            file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return validate(target)

    def test_duplicate_genre_rejected(self):
        result = self.mutate("genres.json", lambda d: d["genres"].append(d["genres"][0]))
        self.assertFalse(result["ok"])
        self.assertTrue(any("duplicate ids" in s for s in result["errors"]))

    def test_unproven_snapshot_source_rejected(self):
        result = self.mutate("research/snapshots_2026_11_16.json",
                             lambda d: d["snapshots"][0].update(source_id="invented"))
        self.assertFalse(result["ok"])
        self.assertTrue(any("unknown source" in s for s in result["errors"]))

    def test_duplicate_rank_rejected(self):
        def broken(data):
            data["snapshots"][0]["entries"][1]["rank"] = 1
        result = self.mutate("research/snapshots_2026_11_16.json", broken)
        self.assertTrue(any("duplicate rank" in s for s in result["errors"]))

    def test_unknown_sentiment_rejected(self):
        result = self.mutate("research/player_signals.json",
                             lambda d: d["items"][0].update(sentiment="probably_good"))
        self.assertFalse(result["ok"])
        self.assertTrue(any("invalid sentiment" in s for s in result["errors"]))

    def test_unsourced_feedback_rejected(self):
        result = self.mutate("research/player_signals.json",
                             lambda d: d["items"][0].update(source_url="https://example.com/no-source"))
        self.assertFalse(result["ok"])
        self.assertTrue(any("missing provenance source" in s for s in result["errors"]))


if __name__ == "__main__":
    unittest.main()
