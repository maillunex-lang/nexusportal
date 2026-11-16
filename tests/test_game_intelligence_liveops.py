import copy
import unittest
from tools.game_intelligence_liveops import ROOT, report, validate_cases
import json

DATA = json.loads((ROOT / "research/live_ops_cases_2026.json").read_text(encoding="utf-8"))
GENRES = {g["id"] for g in json.loads((ROOT / "genres.json").read_text(encoding="utf-8"))["genres"]}


class LiveOpsTests(unittest.TestCase):
    def test_valid_cases(self):
        self.assertEqual(validate_cases(DATA, GENRES), [])

    def test_six_cases(self):
        self.assertEqual(report()["case_count"], 6)

    def test_genre_scoped(self):
        cases = report(genre="mmorpg")["cases"]
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["game"], "SOL: enchant")

    def test_not_annual_ranking(self):
        self.assertFalse(report()["annual_top100_complete"])

    def test_unknown_genre(self):
        with self.assertRaises(ValueError):
            report(genre="fake")

    def mutate(self, fn):
        data = copy.deepcopy(DATA)
        fn(data)
        return validate_cases(data, GENRES)

    def test_duplicate_case_id(self):
        self.assertTrue(self.mutate(lambda d: d["cases"].append(copy.deepcopy(d["cases"][0]))))

    def test_missing_url(self):
        self.assertTrue(self.mutate(lambda d: d["cases"][0].update(source_url="")))

    def test_non_https(self):
        self.assertTrue(self.mutate(lambda d: d["cases"][0].update(source_url="http://example.com")))

    def test_bad_genre(self):
        self.assertTrue(self.mutate(lambda d: d["cases"][0].update(genre_ids=["fake"])))

    def test_bad_date(self):
        self.assertTrue(self.mutate(lambda d: d["cases"][0].update(period="2025-12")))

    def test_missing_limitations(self):
        self.assertTrue(self.mutate(lambda d: d["cases"][0].update(limitations=[])))

    def test_missing_questions(self):
        self.assertTrue(self.mutate(lambda d: d["cases"][0].update(testable_questions=[])))

    def test_annual_rank_claim(self):
        self.assertTrue(self.mutate(lambda d: d["cases"][0].update(rank=1)))

    def test_bad_kind(self):
        self.assertTrue(self.mutate(lambda d: d["cases"][0].update(evidence_type="annual_top100")))

    def test_bad_status(self):
        self.assertTrue(self.mutate(lambda d: d.update(status="top100_complete")))

    def test_empty_cases(self):
        self.assertTrue(self.mutate(lambda d: d.update(cases=[])))


if __name__ == "__main__":
    unittest.main()
