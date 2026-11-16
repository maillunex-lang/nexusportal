"""Offline tests for Game Intelligence evidence and context contract."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.game_intelligence import ROOT, chart_report, blueprint_context, architect_brief, check_url, context, game_catalog, validate


class GameIntelligenceTests(unittest.TestCase):
    def test_valid_starter_dataset(self):
        result = validate()
        self.assertTrue(result["ok"], result["errors"])

    def test_dataset_counts(self):
        result = validate()
        self.assertEqual(result["genre_count"], 12)
        self.assertEqual(result["chart_entries"], 143)
        self.assertEqual(result["player_signals"], 26)
        self.assertEqual(result["genre_blueprints"], 12)
        self.assertEqual(result["editorial_games"], 21)
        self.assertEqual(result["market_insights"], 4)
        self.assertEqual(result["genres_with_top100_complete"], 0)
        self.assertEqual(result["mechanic_templates"], 20)

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
        self.assertEqual(len(result["player_signals"]), 3)
        self.assertEqual(result["player_signals"][0]["game"], "Albion Online")

    def test_mechanic_context_is_genre_scoped(self):
        result = context("arpg")
        self.assertEqual(result["blueprint"]["id"], "arpg")
        self.assertTrue(result["mechanic_templates"])
        self.assertTrue(all("arpg" in t["genres"] for t in result["mechanic_templates"]))

    def test_game_catalog_is_scoped_and_not_ranked(self):
        result = game_catalog("economic_strategy")
        self.assertTrue(any(g["id"] == "capitalism_lab" for g in result["editorial_references"]))
        self.assertIn("NOT", result["ranking_status"])
        self.assertTrue(all("economic_strategy" in g["genres"] for g in result["editorial_references"]))

    def test_game_catalog_rejects_unknown_genre(self):
        with self.assertRaises(ValueError):
            game_catalog("fake_genre")

    def test_pc_only_mobile_rank_rejected(self):
        def broken(data):
            next(g for g in data["games"] if g["id"] == "capitalism_lab")["mobile_rank"] = 1
        result = self.mutate("research/editorial_games.json", broken)
        self.assertFalse(result["ok"])
        self.assertTrue(any("PC-only" in s for s in result["errors"]))

    def test_architect_brief_has_sources_and_risks(self):
        result = architect_brief("economic_strategy")
        self.assertEqual(result["status"], "design_proposal_not_implemented")
        self.assertTrue(result["mvp"])
        self.assertTrue(result["architecture"])
        self.assertTrue(result["pitfalls"])
        self.assertTrue(result["reference_games"])
        self.assertTrue(result["player_feedback"])
        self.assertTrue(all("source_url" in x for x in result["player_feedback"]))

    def test_all_genres_have_blueprints(self):
        genres = json.loads((ROOT / "genres.json").read_text(encoding="utf-8"))["genres"]
        for genre in genres:
            result = architect_brief(genre["id"])
            self.assertEqual(result["status"], "design_proposal_not_implemented")
            self.assertTrue(result["mvp"])
            self.assertTrue(result["open_questions"])

    def test_unknown_genre_rejected(self):
        with self.assertRaises(ValueError):
            context("unknown")

    def test_blueprint_envelope_all_genres(self):
        genres = json.loads((ROOT / "genres.json").read_text())["genres"]
        for g in genres:
            with self.subTest(genre=g["id"]):
                result = blueprint_context(g["id"])
                self.assertEqual(result["schema_version"], "nexus.game-intelligence.context.v1")
                self.assertFalse(result["integration_contract"]["approval_granted"])
                self.assertFalse(result["research_gaps"]["annual_top100_complete"])
                self.assertTrue(result["brief"]["game_dossiers"])
                self.assertTrue(all(g["id"] in d["genre_ids"] for d in result["brief"]["game_dossiers"]))
                source_ids = {x["id"] for x in result["sources"]}
                self.assertTrue(all(set(d["source_ids"]) <= source_ids for d in result["brief"]["game_dossiers"]))
                self.assertNotIn("tasks", result)
                self.assertNotIn("file_scope", result)

    def test_blueprint_feedback_provenance(self):
        result = blueprint_context("mmorpg")
        urls = {s["url"] for s in result["sources"]}
        self.assertTrue(all(s["source_url"] in urls for s in result["brief"]["player_feedback"]))
        self.assertTrue(all(s["published_at"] and s["source_type"] for s in result["brief"]["player_feedback"]))

    def test_blueprint_deterministic(self):
        self.assertEqual(blueprint_context("rts"), blueprint_context("rts"))

    def test_blueprint_unknown_genre(self):
        with self.assertRaises(ValueError):
            blueprint_context("invented")

    def test_blueprint_digest_changes_with_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "data"
            shutil.copytree(ROOT, target)
            before = blueprint_context("rts", target)
            file = target / "research/game_dossiers.json"
            data = json.loads(file.read_text())
            data["dossiers"][0]["design_proposal"]["risk"] += " New caveat."
            file.write_text(json.dumps(data))
            self.assertNotEqual(before["knowledge_digest"], blueprint_context("rts", target)["knowledge_digest"])

    def test_blueprint_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "data"
            shutil.copytree(ROOT, target)
            file = target / "research/game_dossiers.json"
            data = json.loads(file.read_text())
            data["dossiers"][0]["source_ids"] = ["unknown"]
            file.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                blueprint_context("mmorpg", target)

    def test_dossier_counts(self):
        self.assertEqual(validate()["game_dossiers"], 16)

    def test_dossier_duplicate_rejected(self):
        result = self.mutate("research/game_dossiers.json", lambda d: d["dossiers"].append(d["dossiers"][0]))
        self.assertTrue(any("duplicate game" in e for e in result["errors"]))

    def test_dossier_missing_source(self):
        result = self.mutate("research/game_dossiers.json", lambda d: d["dossiers"][0].update(source_ids=["fake"]))
        self.assertTrue(any("missing provenance" in e for e in result["errors"]))

    def test_dossier_missing_fact(self):
        result = self.mutate("research/game_dossiers.json", lambda d: d["dossiers"][0]["facts"].pop("economy"))
        self.assertTrue(any("missing economy" in e for e in result["errors"]))

    def test_dossier_invalid_genre(self):
        result = self.mutate("research/game_dossiers.json", lambda d: d["dossiers"][0].update(genre_ids=["invented"]))
        self.assertFalse(result["ok"])

    def test_dossier_unrelated_review(self):
        result = self.mutate("research/game_dossiers.json", lambda d: d["dossiers"][0].update(review_signal_ids=["caplab_city_1"]))
        self.assertTrue(any("unrelated review" in e for e in result["errors"]))

    def test_dossier_pc_identity_rejected(self):
        result = self.mutate("research/game_dossiers.json", lambda d: next(x for x in d["dossiers"] if x["game_id"] == "capitalism_lab").update(store_identity={"store": "app_store", "app_id": "123"}))
        self.assertTrue(any("PC reference" in e for e in result["errors"]))

    def test_dossier_store_id_must_match_source(self):
        result = self.mutate("research/game_dossiers.json", lambda d: d["dossiers"][0]["store_identity"].update(app_id="wrong_id"))
        self.assertTrue(any("identity not supported" in e for e in result["errors"]))

    def test_dossier_future_date_rejected(self):
        result = self.mutate("research/game_dossiers.json", lambda d: d["dossiers"][0].update(observed_at="2027-01-01"))
        self.assertTrue(any("future observation" in e for e in result["errors"]))

    def test_dossier_missing_caveats_rejected(self):
        result = self.mutate("research/game_dossiers.json", lambda d: d["dossiers"][0].update(limitations=[]))
        self.assertTrue(any("missing limitations" in e for e in result["errors"]))

    def test_every_genre_has_mechanic_contracts(self):
        genres = json.loads((ROOT / "genres.json").read_text())["genres"]
        for g in genres:
            with self.subTest(genre=g["id"]):
                templates = context(g["id"])["mechanic_templates"]
                self.assertTrue(templates)
                self.assertTrue(all(t["contracts"] and t["tests"] for t in templates))

    def test_chart_report_separates_estimates(self):
        result = chart_report("city_builder")
        self.assertEqual(result["distinct_reference_games"], 2)
        self.assertEqual(result["resolved_observations"], 3)
        self.assertEqual(len(result["cohorts"]), 3)
        self.assertEqual(sum(c["is_estimate"] for c in result["cohorts"]), 1)
        self.assertFalse(result["top100_complete"])
        self.assertEqual(result["legacy_observations_excluded"], 143)

    def test_chart_report_keeps_original_category_ranks(self):
        result = chart_report("4x")
        self.assertEqual([r["rank"] for r in result["cohorts"][0]["entries"]], [1, 3, 17])
        self.assertEqual(result["cohorts"][0]["chart_date"], "2026-11-15")
        self.assertEqual(result["cohorts"][0]["observed_at"], "2026-11-16")

    def test_chart_report_unknown_genre(self):
        with self.assertRaises(ValueError):
            chart_report("invented")

    def test_no_chart_evidence_is_explicit(self):
        result = chart_report("naval_strategy")
        self.assertEqual(result["cohorts"], [])
        self.assertEqual(result["distinct_reference_games"], 0)

    def test_chart_sources_in_blueprint_envelope(self):
        result = blueprint_context("city_builder")
        sources = {s["id"] for s in result["sources"]}
        for c in result["chart_evidence"]["cohorts"]:
            self.assertIn(c["source_id"], sources)
            self.assertTrue(all(r["identity_source_id"] in sources for r in c["entries"]))

    def test_new_chart_counts_and_conflicts(self):
        result = validate()
        self.assertEqual(result["resolved_chart_observations"], 7)
        self.assertEqual(result["legacy_chart_date_conflicts"], 3)

    def test_chart_duplicate_rank_rejected(self):
        result = self.mutate("research/resolved_charts.json", lambda d: d["batches"][0]["entries"][1].update(rank=1))
        self.assertTrue(any("duplicate rank" in e for e in result["errors"]))

    def test_chart_boolean_rank_rejected(self):
        result = self.mutate("research/resolved_charts.json", lambda d: d["batches"][0]["entries"][0].update(rank=True))
        self.assertFalse(result["ok"])

    def test_chart_duplicate_identity_rejected(self):
        result = self.mutate("research/resolved_charts.json", lambda d: d["batches"][0]["entries"].append(dict(d["batches"][0]["entries"][0], rank=100)))
        self.assertTrue(any("duplicate app identity" in e for e in result["errors"]))

    def test_chart_wrong_identity_rejected(self):
        result = self.mutate("research/resolved_charts.json", lambda d: d["batches"][0]["entries"][0].update(app_id="wrong.package"))
        self.assertTrue(any("identity mismatch" in e for e in result["errors"]))

    def test_chart_pc_game_rejected(self):
        result = self.mutate("research/resolved_charts.json", lambda d: d["batches"][0]["entries"][0].update(game_id="capitalism_lab"))
        self.assertFalse(result["ok"])

    def test_chart_missing_identity_provenance_rejected(self):
        result = self.mutate("research/resolved_charts.json", lambda d: d["batches"][0]["entries"][0].update(identity_source_id="fake"))
        self.assertTrue(any("identity provenance" in e for e in result["errors"]))

    def test_chart_wrong_country_rejected(self):
        result = self.mutate("research/resolved_charts.json", lambda d: d["batches"][0].update(country="JP"))
        self.assertTrue(any("country mismatch" in e for e in result["errors"]))

    def test_chart_wrong_date_rejected(self):
        result = self.mutate("research/resolved_charts.json", lambda d: d["batches"][0].update(chart_date="2026-11-16"))
        self.assertTrue(any("chart_date mismatch" in e for e in result["errors"]))

    def test_chart_future_date_rejected(self):
        result = self.mutate("research/resolved_charts.json", lambda d: d["batches"][0].update(chart_date="2027-01-01"))
        self.assertTrue(any("impossible date" in e for e in result["errors"]))

    def test_chart_estimate_cannot_become_official(self):
        result = self.mutate("research/resolved_charts.json", lambda d: d["batches"][1].update(is_estimate=False))
        self.assertTrue(any("estimate label" in e for e in result["errors"]))

    def test_chart_duplicate_cohort_rejected(self):
        result = self.mutate("research/resolved_charts.json", lambda d: d["batches"].append(dict(d["batches"][0], id="other_id")))
        self.assertTrue(any("duplicate cohort" in e for e in result["errors"]))

    def test_chart_empty_genre_provenance_rejected(self):
        result = self.mutate("research/resolved_charts.json", lambda d: d["batches"][0]["entries"][0].update(genre_source_ids=[]))
        self.assertFalse(result["ok"])

    def test_legacy_audit_required(self):
        result = self.mutate("research/chart_audit.json", lambda d: d["items"].pop())
        self.assertTrue(any("exactly one audit" in e for e in result["errors"]))

    def test_legacy_cannot_enter_resolved_report(self):
        result = self.mutate("research/chart_audit.json", lambda d: d["items"][0].update(eligible_for_resolved_reports=True))
        self.assertTrue(any("unresolved legacy" in e for e in result["errors"]))

    def test_review_publication_cannot_follow_observation(self):
        result = self.mutate("research/player_signals.json", lambda d: d["items"][-1].update(published_at="2026-11-17"))
        self.assertTrue(any("publication after observation" in e for e in result["errors"]))

    def test_review_future_observation_rejected(self):
        result = self.mutate("research/player_signals.json", lambda d: d["items"][-1].update(observed_at="2027-01-01"))
        self.assertTrue(any("future observation" in e for e in result["errors"]))

    def test_review_requires_locator(self):
        result = self.mutate("research/player_signals.json", lambda d: d["items"][-1].pop("locator"))
        self.assertTrue(any("locator" in e for e in result["errors"]))

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

    def test_bad_template_genre_rejected(self):
        result = self.mutate("mechanic_templates.json",
                             lambda d: d["templates"][0]["genres"].append("not_a_genre"))
        self.assertFalse(result["ok"])
        self.assertTrue(any("unknown genre" in s for s in result["errors"]))

    def test_missing_genre_coverage_rejected(self):
        result = self.mutate("research/coverage_2026.json",
                             lambda d: d["genres"].pop())
        self.assertFalse(result["ok"])
        self.assertTrue(any("coverage" in e for e in result["errors"]))

    def test_market_source_required(self):
        result = self.mutate("research/market_2026.json",
                             lambda d: d["insights"][0].update(source="unverified"))
        self.assertFalse(result["ok"])
        self.assertTrue(any("market: invalid source" in e for e in result["errors"]))

    def test_unsourced_feedback_rejected(self):
        result = self.mutate("research/player_signals.json",
                             lambda d: d["items"][0].update(source_url="https://example.com/no-source"))
        self.assertFalse(result["ok"])
        self.assertTrue(any("missing provenance source" in s for s in result["errors"]))


if __name__ == "__main__":
    unittest.main()
