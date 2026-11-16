import copy
import json
import unittest
from pathlib import Path

from tools.adaptive_project import prompt, schedule, scope_overlap, validate

PLAN = json.loads((Path(__file__).resolve().parents[1] / "docs/adaptive_project/example_plan.json").read_text(encoding="utf-8"))


class AdaptiveProjectTests(unittest.TestCase):
    def test_valid_plan(self):
        self.assertEqual(validate(PLAN), [])

    def test_parallel_independent_tasks(self):
        result = schedule(PLAN)
        self.assertEqual(result["parallel_batches"][0], ["A1", "A2"])
        self.assertEqual({x["id"] for x in result["blocked"]}, {"A3", "A4", "A5"})

    def test_prompt_is_copy_ready(self):
        text = prompt(PLAN, "A1")
        self.assertIn("Критерии приёмки", text)
        self.assertIn("Не пушить в main", text)
        self.assertIn("docs/network/**", text)
        self.assertIn("не сливать автоматически", text)

    def test_blocked_prompt_rejected(self):
        with self.assertRaisesRegex(ValueError, "blocked"):
            prompt(PLAN, "A3")

    def test_accepted_dependencies_unlock(self):
        plan = copy.deepcopy(PLAN)
        plan["tasks"][0]["status"] = "accepted"
        result = schedule(plan)
        self.assertIn("A3", result["parallel_batches"][0])
        self.assertIn("A4", result["parallel_batches"][0])

    def test_tests_passed_is_not_accepted(self):
        plan = copy.deepcopy(PLAN)
        plan["tasks"][0]["status"] = "tests_passed"
        self.assertNotIn("A3", schedule(plan)["parallel_batches"][0])

    def test_cycle_rejected(self):
        plan = copy.deepcopy(PLAN)
        plan["tasks"][0]["dependencies"] = ["A3"]
        self.assertTrue(any("cycle" in e for e in validate(plan)))

    def test_missing_dependency_rejected(self):
        plan = copy.deepcopy(PLAN)
        plan["tasks"][0]["dependencies"] = ["UNKNOWN"]
        self.assertTrue(validate(plan))

    def test_duplicate_id_rejected(self):
        plan = copy.deepcopy(PLAN)
        plan["tasks"].append(copy.deepcopy(plan["tasks"][0]))
        self.assertTrue(validate(plan))

    def test_absolute_path_rejected(self):
        plan = copy.deepcopy(PLAN)
        plan["tasks"][0]["file_scopes"] = ["/etc/passwd"]
        self.assertTrue(validate(plan))

    def test_path_traversal_rejected(self):
        plan = copy.deepcopy(PLAN)
        plan["tasks"][0]["file_scopes"] = ["../secrets"]
        self.assertTrue(validate(plan))

    def test_unknown_status_rejected(self):
        plan = copy.deepcopy(PLAN)
        plan["tasks"][0]["status"] = "claimed_done"
        self.assertTrue(validate(plan))

    def test_overlap_exact(self):
        self.assertTrue(scope_overlap(["client/ui/**"], ["client/ui/**"]))

    def test_overlap_wildcard(self):
        self.assertTrue(scope_overlap(["server/ships/**"], ["server/ships/api.py"]))

    def test_disjoint_scopes(self):
        self.assertFalse(scope_overlap(["client/ui/**"], ["server/ships/**"]))

    def test_unknown_task_prompt(self):
        with self.assertRaisesRegex(ValueError, "unknown task"):
            prompt(PLAN, "UNKNOWN")

    def test_missing_gdd_rejected(self):
        plan = copy.deepcopy(PLAN)
        plan["gdd_refs"] = []
        self.assertTrue(validate(plan))


if __name__ == "__main__":
    unittest.main()
