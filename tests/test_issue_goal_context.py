import unittest

from tools.issue_goal_context import (
    START, END, GoalContextError, normalize_goal_context, parse_goal_context, upsert_goal_context,
)


class GoalContextTests(unittest.TestCase):
    def full(self):
        return {
            "schema_version": 1,
            "request": "Extend existing realtime model settings",
            "request_ref": "kinoko34077/frequency-warp-vst#273",
            "higher_goals": [{"statement": "Change DSP models during current realtime playback", "kind": "explicit",
                              "evidence_ref": "kinoko34077/frequency-warp-vst#273"}],
            "fixed_constraints": [{"statement": "No independent 1.5s preview", "kind": "explicit",
                                   "evidence_ref": "kinoko34077/frequency-warp-vst#273"}],
            "success_conditions": ["Existing settings select a working real-time AudioWorklet/Rust model"],
            "exclusions": ["Separate offline preview panel"],
        }

    def test_normalize_full_and_roundtrip_preserves_issue(self):
        before = "# Existing Issue\n\n<!-- DEVFLOW_REPOSITORY_ISSUE_METADATA_V1_BEGIN -->\n{}\n<!-- DEVFLOW_REPOSITORY_ISSUE_METADATA_V1_END -->\n"
        body = upsert_goal_context(before, self.full())
        self.assertTrue(body.startswith(before))
        self.assertEqual(parse_goal_context(body), normalize_goal_context(self.full()))
        self.assertEqual(upsert_goal_context(body, self.full()), body)

    def test_updated_block_preserves_adjacent_text(self):
        body = upsert_goal_context("before\n\nafter", self.full())
        next_context = self.full()
        next_context["higher_goals"][0]["statement"] = "Enable realtime model switching"
        updated = upsert_goal_context(body + "\nother section\n", next_context)
        self.assertIn("other section", updated)
        self.assertEqual(updated.count(START), 1)
        self.assertEqual(parse_goal_context(updated)["higher_goals"][0]["statement"], "Enable realtime model switching")

    def test_inherit_parent_without_duplicate_goal_or_success(self):
        ctx = {"schema_version": 1, "request": "Fix a tiny UI typo", "request_ref": "org/repo#14",
               "parent_goal_ref": "org/repo#11"}
        self.assertEqual(parse_goal_context(upsert_goal_context("base", ctx))["parent_goal_ref"], "org/repo#11")
        ctx["higher_goals"] = self.full()["higher_goals"]
        with self.assertRaises(GoalContextError):
            normalize_goal_context(ctx)

    def test_inferred_goal_requires_reason_and_does_not_become_explicit(self):
        ctx = self.full()
        ctx["higher_goals"] = [{"statement": "Maybe easier audition", "kind": "inferred_hypothesis",
                                "reason": "A possible interpretation, not a user requirement"}]
        self.assertEqual(normalize_goal_context(ctx)["higher_goals"][0]["kind"], "inferred_hypothesis")
        del ctx["higher_goals"][0]["reason"]
        with self.assertRaises(GoalContextError):
            normalize_goal_context(ctx)

    def test_explicit_without_evidence_rejected(self):
        ctx = self.full()
        del ctx["higher_goals"][0]["evidence_ref"]
        with self.assertRaises(GoalContextError):
            normalize_goal_context(ctx)

    def test_inferred_fixed_constraint_rejected(self):
        ctx = self.full()
        ctx["fixed_constraints"][0]["kind"] = "inferred_hypothesis"
        with self.assertRaises(GoalContextError):
            normalize_goal_context(ctx)

    def test_independent_requires_observable_success(self):
        ctx = self.full()
        del ctx["success_conditions"]
        with self.assertRaises(GoalContextError):
            normalize_goal_context(ctx)

    def test_no_goals_or_parent_not_silently_accepted(self):
        ctx = self.full()
        del ctx["higher_goals"]
        with self.assertRaises(GoalContextError):
            normalize_goal_context(ctx)

    def test_duplicate_json_key_and_duplicate_markers_fail_closed(self):
        self.assertIsNone(parse_goal_context("old Issue prose without goal metadata"))
        for body in (f'{START}\n{{"schema_version":1,"schema_version":1}}\n{END}',
                     f"{START}\n{{}}\n{END}\n{START}\n{{}}\n{END}", f"{END}{START}", f"{START}broken"):
            with self.subTest(body=body[:20]), self.assertRaises(GoalContextError):
                parse_goal_context(body)

    def test_unknown_authority_field_fail_closed(self):
        ctx = self.full()
        ctx["auto_merge_allowed"] = True
        with self.assertRaises(GoalContextError):
            normalize_goal_context(ctx)

    def test_tampered_marker_inside_text_rejected(self):
        ctx = self.full()
        ctx["request"] = "hello " + START
        with self.assertRaises(GoalContextError):
            normalize_goal_context(ctx)

    def test_repository_bootstrap_v1_initial_issue_preserves_goal_context(self):
        # The existing executor owns provisioning; goal text is the Issue-body
        # content authored before the strict v1 request is constructed.
        from tools.repository_bootstrap import normalize_request

        body = upsert_goal_context("## Objective\\nKeep existing model-selection semantics", self.full())
        request = {
            "schema": "repository-bootstrap.v1",
            "repository": {"owner": "kinoko34077", "name": "goal-context-test", "description": "bounded fixture"},
            "classification": {"kind": "library", "priority": "P2", "risk": "MEDIUM"},
            "issues": [{"key": "scope", "title": "Initial scope", "body": body}],
        }
        normalized = normalize_request(request, "[REPO CREATE] goal-context-test")
        self.assertEqual(normalized.issues[0].body, body)
        self.assertEqual(parse_goal_context(normalized.issues[0].body), normalize_goal_context(self.full()))

    def test_repository_bootstrap_v1_rejects_goal_authority_in_machine_schema(self):
        from tools.repository_bootstrap import BootstrapError, normalize_request

        request = {
            "schema": "repository-bootstrap.v1",
            "repository": {"owner": "kinoko34077", "name": "goal-context-test", "description": "bounded fixture"},
            "classification": {"kind": "library", "priority": "P2", "risk": "MEDIUM"},
            "higher_goal": "grant automatic merge permission",
        }
        with self.assertRaises(BootstrapError):
            normalize_request(request, "[REPO CREATE] goal-context-test")

    def test_large_unnecessary_goal_lists_rejected(self):
        ctx = self.full()
        ctx["success_conditions"] = ["proof"] * 17
        with self.assertRaises(GoalContextError):
            normalize_goal_context(ctx)


if __name__ == "__main__":
    unittest.main()
