import unittest
import json

from tools import issue_goal_context
from tools.issue_goal_context import (
    START, END, GoalContextError, normalize_goal_context, parse_goal_context, upsert_goal_context,
)

V2_START = "<!-- DEVFLOW_ISSUE_GOAL_CONTEXT_V2_BEGIN -->"
V2_END = "<!-- DEVFLOW_ISSUE_GOAL_CONTEXT_V2_END -->"


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
                     f'{V2_START}\n{{"schema_version":2,"schema_version":2}}\n{V2_END}',
                     f"{START}\n{{}}\n{END}\n{START}\n{{}}\n{END}", f"{END}{START}", f"{START}broken"):
            with self.subTest(body=body[:20]), self.assertRaises(GoalContextError):
                parse_goal_context(body)
        mixed = upsert_goal_context("base", self.full()) + upsert_goal_context("base", self.v2_context([]))
        with self.assertRaises(GoalContextError):
            parse_goal_context(mixed)

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

    def test_v2_rejects_reserved_markers_in_nested_specification_values_and_keys(self):
        cases = (
            {"text": f"quoted {V2_END} marker"},
            {V2_START: "marker in object key"},
            {"nested": [{"deeper": {"text": f"quoted {END} marker"}}]},
        )
        for value in cases:
            with self.subTest(value=value):
                context = self.v2_context([self.claim("marker", "runtime.option", value)])
                with self.assertRaisesRegex(GoalContextError, "reserved marker"):
                    normalize_goal_context(context)

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

    def test_v2_preserves_falsy_values_v1_roundtrips_and_downgrade_is_rejected(self):
        ctx = self.v2_context([
            self.claim("zero", "audio.cutoff_hz", 0),
            self.claim("disabled", "feature.enabled", False),
            self.claim("nullable", "feature.option", None),
        ])
        ctx["fixed_constraints"] = self.full()["fixed_constraints"]
        normalized = normalize_goal_context(ctx)
        self.assertEqual(normalized["schema_version"], 2)
        self.assertEqual([item.get("value") for item in normalized["specifications"]], [0, False, None])
        body = upsert_goal_context("## Original prose\nKeep this", ctx)
        self.assertIn(V2_START, body)
        self.assertEqual(parse_goal_context(body), normalized)
        v1_body = upsert_goal_context("## Original prose\nKeep this", self.full())
        self.assertEqual(parse_goal_context(v1_body), normalize_goal_context(self.full()))
        upgraded = upsert_goal_context(v1_body, ctx)
        self.assertIn("## Original prose\nKeep this", upgraded)
        self.assertIn(V2_START, upgraded)
        self.assertNotIn(START, upgraded)
        with self.assertRaisesRegex(GoalContextError, "cannot downgrade"):
            upsert_goal_context(upgraded, self.full())

    def test_v2_rejects_hypothesis_promoted_to_adopted(self):
        ctx = self.v2_context([self.claim("guess", "runtime.binding", "SECRET", authority="inferred_hypothesis")])
        with self.assertRaisesRegex(GoalContextError, "inferred_hypothesis cannot be adopted"):
            normalize_goal_context(ctx)

    def test_parent_resolution_applies_only_exact_scoped_override_and_keeps_proposal(self):
        parent_context = self.v2_context([
            self.claim("base-url", "site.base_url", "https://example.test", scope="web"),
            self.claim("phase-zero", "audio.cutoff_hz", 0, scope="runtime"),
            self.claim("disabled", "feature.enabled", False, scope="runtime"),
            self.claim("nullable", "feature.option", None, scope="runtime"),
        ])
        parent_context["fixed_constraints"] = [{
            "statement": "Keep the existing runtime path",
            "kind": "accepted_spec",
            "evidence_ref": "https://sources.example/runtime-path",
        }]
        parent = self.make_issue("org/repo", 11, parent_context)
        child = self.make_issue("org/repo", 14, self.v2_context([
            self.claim("new-url", "site.base_url", "https://preview.example.test", scope="web",
                       supersedes="org/repo#11:base-url"),
            self.claim("runtime-proposal", "feature.enabled", True, scope="runtime", state="proposed",
                       authority="inferred_hypothesis", reason="Unaccepted alternative"),
        ], parent_goal_ref="org/repo#11"))
        issues = {("org/repo", 11): parent}

        result = issue_goal_context.resolve_goal_context(child, lambda repo, number: issues[(repo, number)])
        effective = {(item["key"], item["scope"]): item for item in result["effective_specifications"]}
        self.assertEqual(result["parent_chain_status"], "COMPLETE")
        self.assertEqual(result["coverage"]["structured_specifications"], "RECORDED_CLAIMS_ONLY")
        self.assertEqual(effective[("site.base_url", "web")]["value"], "https://preview.example.test")
        self.assertEqual(effective[("audio.cutoff_hz", "runtime")]["value"], 0)
        self.assertIs(effective[("feature.enabled", "runtime")]["value"], False)
        self.assertIsNone(effective[("feature.option", "runtime")]["value"])
        self.assertEqual(result["proposals"][0]["claim_ref"], "org/repo#14:runtime-proposal")
        self.assertEqual(result["proposals"][0]["state"], "proposed")
        self.assertEqual(effective[("audio.cutoff_hz", "runtime")]["source_issue"], "org/repo#11")
        self.assertEqual(effective[("site.base_url", "web")]["evidence_ref"], "https://sources.example/accepted")
        self.assertEqual(result["source_contexts"][-1]["context"]["parent_goal_ref"], "org/repo#11")
        self.assertEqual(result["source_contexts"][0]["context"]["fixed_constraints"][0]["evidence_ref"],
                         "https://sources.example/runtime-path")

    def test_latest_explicit_correction_supersedes_only_the_previous_source_claim(self):
        root = self.make_issue("org/repo", 11, self.v2_context([
            self.claim("mode-v1", "runtime.mode", "safe"),
            self.claim("proposal", "runtime.new_mode", "experimental", state="proposed",
                       authority="inferred_hypothesis", reason="Unaccepted alternative"),
        ]))
        middle = self.make_issue("org/repo", 14, self.v2_context([
            self.claim("mode-v2", "runtime.mode", "balanced", supersedes="org/repo#11:mode-v1"),
        ], parent_goal_ref="org/repo#11"))
        leaf = self.make_issue("org/repo", 20, self.v2_context([
            self.claim("mode-v3", "runtime.mode", "responsive", supersedes="org/repo#14:mode-v2"),
            self.claim("proposal-adopted", "runtime.new_mode", "experimental", authority="accepted_spec"),
        ], parent_goal_ref="org/repo#14"))
        issues = {("org/repo", 11): root, ("org/repo", 14): middle}
        result = issue_goal_context.resolve_goal_context(leaf, lambda repo, number: issues[(repo, number)])
        effective = {(item["key"], item["scope"]): item for item in result["effective_specifications"]}
        self.assertEqual(effective[("runtime.mode", "default")]["value"], "responsive")
        self.assertEqual(effective[("runtime.new_mode", "default")]["value"], "experimental")
        history = {item["id"]: item["resolution_status"] for item in result["specifications"]}
        self.assertEqual(history["mode-v1"], "SUPERSEDED")
        self.assertEqual(history["mode-v2"], "SUPERSEDED")
        self.assertEqual(history["mode-v3"], "EFFECTIVE")

    def test_explicit_removal_is_distinct_from_absence_and_does_not_remove_sibling(self):
        parent = self.make_issue("org/repo", 11, self.v2_context([
            self.claim("url", "site.base_url", "https://example.test", scope="web"),
            self.claim("timeout", "request.timeout_s", 30, scope="runtime"),
        ]))
        child = self.make_issue("org/repo", 14, self.v2_context([
            self.claim("remove-url", "site.base_url", None, scope="web", state="removed",
                       supersedes="org/repo#11:url"),
        ], parent_goal_ref="org/repo#11"))
        result = issue_goal_context.resolve_goal_context(child, lambda _repo, _number: parent)
        effective = {(item["key"], item["scope"]): item for item in result["effective_specifications"]}
        self.assertEqual(effective[("site.base_url", "web")]["state"], "removed")
        self.assertNotIn("value", effective[("site.base_url", "web")])
        self.assertEqual(effective[("request.timeout_s", "runtime")]["value"], 30)

    def test_unavailable_parent_stays_unknown_without_leaking_reader_error(self):
        parent = self.make_issue("org/repo", 11, self.v2_context([
            self.claim("base-flag", "feature.enabled", True),
            self.claim("runtime-mode", "runtime.mode", "fast"),
        ], parent_goal_ref="private/repo#99"))
        child = self.make_issue("org/repo", 14, self.v2_context([
            self.claim("local-flag", "feature.enabled", False, supersedes="org/repo#11:base-flag"),
            self.claim("child-only", "feature.new_setting", "enabled"),
        ], parent_goal_ref="org/repo#11"))

        failures = (PermissionError("403 private response body and token must not appear"),
                    FileNotFoundError("404 private response body and token must not appear"))
        for failure in failures:
            def unavailable(repository, number, observed=failure):
                if (repository, number) == ("org/repo", 11):
                    return parent
                raise observed

            with self.subTest(error=type(failure).__name__):
                result = issue_goal_context.resolve_goal_context(child, unavailable)
                self.assertEqual(result["parent_chain_status"], "PARTIAL_UNKNOWN")
                effective = {item["key"]: item for item in result["effective_specifications"]}
                self.assertEqual(set(effective), {"feature.enabled", "runtime.mode", "feature.new_setting"})
                self.assertTrue(all(item["state"] == "unknown" for item in effective.values()))
                self.assertTrue(all(item["reason_code"] == "PARENT_CHAIN_INCOMPLETE" for item in effective.values()))
                self.assertNotIn("value", effective["feature.enabled"])
                self.assertEqual(result["coverage"]["structured_specifications"], "PARTIAL_UNKNOWN")
                self.assertEqual(result["unknowns"][0]["reason_code"], "PARENT_UNAVAILABLE")
                self.assertNotIn("private response body", json.dumps(result))
                self.assertNotIn("token", json.dumps(result))
                self.assertNotIn("private/repo", json.dumps(result))
                self.assertNotIn("parent_goal_ref", result["source_contexts"][0]["context"])
                self.assertEqual(result["source_contexts"][1]["context"]["parent_goal_ref"], "org/repo#11")
                visible = {item["id"]: item for item in result["specifications"]}
                self.assertEqual(visible["local-flag"]["value"], False)
                self.assertEqual(visible["local-flag"]["resolution_status"], "PENDING_PARENT_UNKNOWN")

    def test_parent_identity_mismatch_and_cycle_are_unknown(self):
        child = self.make_issue("org/repo", 14, self.v2_context([
            self.claim("visible-child", "feature.enabled", False),
        ], parent_goal_ref="org/repo#11"))
        wrong = self.make_issue("other/repo", 11, self.v2_context([], parent_goal_ref="org/repo#14"))
        mismatch = issue_goal_context.resolve_goal_context(child, lambda _repo, _number: wrong)
        self.assertEqual(mismatch["unknowns"][0]["reason_code"], "PARENT_IDENTITY_MISMATCH")
        self.assertEqual(mismatch["effective_specifications"][0]["state"], "unknown")
        self.assertEqual(mismatch["effective_specifications"][0]["reason_code"], "PARENT_CHAIN_INCOMPLETE")

        parent = self.make_issue("org/repo", 11, self.v2_context([], parent_goal_ref="org/repo#14"))
        cycle = issue_goal_context.resolve_goal_context(child, lambda _repo, _number: parent if _number == 11 else child)
        self.assertEqual(cycle["unknowns"][0]["reason_code"], "PARENT_CYCLE")
        self.assertEqual(cycle["effective_specifications"][0]["state"], "unknown")
        self.assertEqual(cycle["effective_specifications"][0]["reason_code"], "PARENT_CHAIN_INCOMPLETE")

        missing_parent = {"repository": "org/repo", "issue_number": 11,
                          "url": "https://github.com/org/repo/issues/11", "body": ""}
        missing_context = issue_goal_context.resolve_goal_context(child, lambda _repo, _number: missing_parent)
        self.assertEqual(missing_context["unknowns"][0]["reason_code"], "GOAL_CONTEXT_MISSING")
        self.assertEqual(missing_context["effective_specifications"][0]["state"], "unknown")

        malformed_parent = self.make_issue("org/repo", 11, self.v2_context([]))
        malformed_parent["body"] = f"{V2_START}\n{{malformed json}}\n{V2_END}"
        malformed = issue_goal_context.resolve_goal_context(child, lambda _repo, _number: malformed_parent)
        self.assertEqual(malformed["unknowns"][0]["reason_code"], "GOAL_CONTEXT_INVALID")
        self.assertEqual(malformed["parent_chain_status"], "PARTIAL_UNKNOWN")
        self.assertEqual(malformed["effective_specifications"][0]["state"], "unknown")
        self.assertEqual(malformed["effective_specifications"][0]["reason_code"], "PARENT_CHAIN_INCOMPLETE")
        self.assertNotIn("value", malformed["effective_specifications"][0])

        malformed = self.make_issue("org/repo", 14, self.v2_context([], parent_goal_ref="https://["))
        invalid_ref = issue_goal_context.resolve_goal_context(malformed, lambda _repo, _number: None)
        self.assertEqual(invalid_ref["unknowns"][0]["reason_code"], "PARENT_REF_INVALID")

    def test_v1_narrative_chain_does_not_claim_structured_specification_coverage(self):
        body = upsert_goal_context("existing request", self.full())
        issue = {"repository": "org/repo", "issue_number": 14,
                 "url": "https://github.com/org/repo/issues/14", "body": body}
        result = issue_goal_context.resolve_goal_context(issue, lambda _repo, _number: None)
        self.assertEqual(result["parent_chain_status"], "COMPLETE")
        self.assertEqual(result["coverage"]["structured_specifications"], "NOT_REPRESENTED")
        self.assertEqual(result["effective_specifications"], [])
        self.assertEqual(result["source_contexts"][0]["context"]["request_ref"], self.full()["request_ref"])

    def test_missing_context_and_depth_limit_remain_explicitly_unknown(self):
        no_marker = {"repository": "org/repo", "issue_number": 14,
                     "url": "https://github.com/org/repo/issues/14", "body": "## No context"}
        missing = issue_goal_context.resolve_goal_context(no_marker, lambda _repo, _number: None)
        self.assertEqual(missing["parent_chain_status"], "UNKNOWN")
        self.assertEqual(missing["unknowns"][0]["reason_code"], "GOAL_CONTEXT_MISSING")

        child = self.make_issue("org/repo", 14, self.v2_context([
            self.claim("limited-claim", "runtime.mode", "safe"),
        ], parent_goal_ref="org/repo#11"))
        limited = issue_goal_context.resolve_goal_context(child, lambda _repo, _number: None, max_depth=1)
        self.assertEqual(limited["parent_chain_status"], "PARTIAL_UNKNOWN")
        self.assertEqual(limited["unknowns"][0]["reason_code"], "PARENT_DEPTH_LIMIT")
        self.assertEqual(limited["effective_specifications"][0]["state"], "unknown")
        self.assertEqual(limited["effective_specifications"][0]["reason_code"], "PARENT_CHAIN_INCOMPLETE")

    def test_conflicting_same_scope_supersessions_produce_unknown_not_last_writer_wins(self):
        parent = self.make_issue("org/repo", 11, self.v2_context([
            self.claim("old", "runtime.mode", "safe"),
        ]))
        child = self.make_issue("org/repo", 14, self.v2_context([
            self.claim("new-a", "runtime.mode", "fast", supersedes="org/repo#11:old"),
            self.claim("new-b", "runtime.mode", "balanced", supersedes="org/repo#11:old"),
        ], parent_goal_ref="org/repo#11"))
        result = issue_goal_context.resolve_goal_context(child, lambda _repo, _number: parent)
        current = next(item for item in result["effective_specifications"] if item["key"] == "runtime.mode")
        self.assertEqual(current["state"], "unknown")
        self.assertEqual(current["reason_code"], "CONFLICTING_OVERRIDES")
        self.assertNotIn("value", current)

    def test_wrong_key_or_scope_supersedes_does_not_conflict_unrelated_claim(self):
        parent = self.make_issue("org/repo", 11, self.v2_context([
            self.claim("target", "runtime.mode", "safe"),
            self.claim("other-key", "feature.enabled", True),
            self.claim("other-scope", "runtime.mode", "preview", scope="preview"),
        ]))
        cases = (
            ("other-key", "runtime.mode", "default"),
            ("other-scope", "runtime.mode", "default"),
        )
        for target_claim_id, key, scope in cases:
            with self.subTest(target_claim_id=target_claim_id):
                child = self.make_issue("org/repo", 14, self.v2_context([
                    self.claim("child", key, "balanced", scope=scope,
                               supersedes=f"org/repo#11:{target_claim_id}"),
                ], parent_goal_ref="org/repo#11"))
                result = issue_goal_context.resolve_goal_context(child, lambda _repo, _number: parent)
                effective = {(item["key"], item["scope"]): item for item in result["effective_specifications"]}
                history = {item["claim_ref"]: item["resolution_status"] for item in result["specifications"]}
                conflict = effective[("runtime.mode", "default")]

                self.assertEqual(conflict["state"], "unknown")
                self.assertEqual(conflict["reason_code"], "CONFLICTING_OVERRIDES")
                self.assertEqual(set(conflict["conflicting_claim_refs"]), {
                    "org/repo#11:target", "org/repo#14:child",
                })
                self.assertEqual(conflict["invalid_supersedes_ref"], f"org/repo#11:{target_claim_id}")
                self.assertEqual(history["org/repo#11:target"], "CONFLICTED")
                self.assertEqual(history["org/repo#14:child"], "CONFLICTED")
                unrelated = ("org/repo#11:" + target_claim_id)
                self.assertNotEqual(history[unrelated], "CONFLICTED")
                if target_claim_id == "other-key":
                    self.assertEqual(effective[("feature.enabled", "default")]["value"], True)
                    self.assertEqual(history["org/repo#11:other-key"], "EFFECTIVE")
                else:
                    self.assertEqual(effective[("runtime.mode", "preview")]["value"], "preview")
                    self.assertEqual(history["org/repo#11:other-scope"], "EFFECTIVE")

    def test_source_backed_zero_unknown_and_build_runtime_fixtures_remain_distinct(self):
        frequency_ref = "https://github.com/kinoko34077/frequency-warp-vst/issues/3"
        frequency = self.make_issue("org/frequency", 3, self.v2_context([
            self.claim("negative-mode", "frequency.below_zero_mode", ["Reflect", "Kill", "Fade"],
                       authority="accepted_spec", evidence_ref=frequency_ref),
            self.claim("exact-zero-mapping", "frequency.g_at_zero", None, state="unknown",
                       authority="accepted_spec", evidence_ref=frequency_ref,
                       reason="The canonical spec marks g(f)=0 handling unresolved"),
        ], request_ref=frequency_ref))
        frequency_result = issue_goal_context.resolve_goal_context(frequency, lambda _repo, _number: None)
        frequency_values = {item["key"]: item for item in frequency_result["effective_specifications"]}
        self.assertEqual(frequency_values["frequency.below_zero_mode"]["value"], ["Reflect", "Kill", "Fade"])
        self.assertEqual(frequency_values["frequency.g_at_zero"]["state"], "unknown")
        self.assertNotIn("value", frequency_values["frequency.g_at_zero"])

        gomoku_ref = "https://github.com/kinoko34077/Gomoku-5D/issues/10"
        gomoku = self.make_issue("kinoko34077/Gomoku-5D", 10, self.v2_context([
            self.claim("first-phase-v1", "game.first_placement_phase", 1,
                       authority="accepted_spec", evidence_ref=gomoku_ref),
            self.claim("first-phase-v2", "game.first_placement_phase", 0,
                       authority="accepted_spec", evidence_ref=gomoku_ref,
                       supersedes="kinoko34077/Gomoku-5D#10:first-phase-v1"),
        ], request_ref=gomoku_ref))
        gomoku_result = issue_goal_context.resolve_goal_context(gomoku, lambda _repo, _number: None)
        self.assertEqual(gomoku_result["effective_specifications"][0]["value"], 0)
        self.assertEqual(gomoku_result["effective_specifications"][0]["evidence_ref"], gomoku_ref)
        gomoku_history = {item["id"]: item["resolution_status"] for item in gomoku_result["specifications"]}
        self.assertEqual(gomoku_history["first-phase-v1"], "SUPERSEDED")
        self.assertEqual(gomoku_history["first-phase-v2"], "EFFECTIVE")

        cloudflare_ref = "https://github.com/kinoko34077/kinotch-judgment-learning/issues/31"
        cloudflare = self.make_issue("org/cloudflare-config", 31, self.v2_context([
            self.claim("build-client-id", "github.client_id.configured", True, scope="build",
                       authority="source_derived", evidence_ref=cloudflare_ref),
            self.claim("runtime-client-id", "github.client_id.configured", False, scope="runtime",
                       authority="source_derived", evidence_ref=cloudflare_ref),
        ], request_ref=cloudflare_ref))
        cloudflare_result = issue_goal_context.resolve_goal_context(cloudflare, lambda _repo, _number: None)
        scoped = {(item["key"], item["scope"]): item for item in cloudflare_result["effective_specifications"]}
        self.assertIs(scoped[("github.client_id.configured", "build")]["value"], True)
        self.assertIs(scoped[("github.client_id.configured", "runtime")]["value"], False)

    @staticmethod
    def claim(claim_id, key, value, *, scope="default", state="adopted", authority="accepted_spec",
              supersedes=None, reason=None, evidence_ref="https://sources.example/accepted"):
        item = {"id": claim_id, "key": key, "scope": scope, "state": state,
                "authority": authority, "evidence_ref": evidence_ref}
        if state != "removed" and state != "unknown":
            item["value"] = value
        if supersedes is not None:
            item["supersedes"] = supersedes
        if reason is not None:
            item["reason"] = reason
        elif state in {"unknown", "proposed"}:
            item["reason"] = "Recorded as unaccepted or unresolved"
        return item

    @staticmethod
    def v2_context(specifications, *, parent_goal_ref=None, request_ref="org/repo#1"):
        result = {"schema_version": 2, "request": "Keep the source request", "request_ref": request_ref,
                  "specifications": specifications}
        if parent_goal_ref is None:
            result["higher_goals"] = [{"statement": "Preserve the accepted project behavior", "kind": "explicit",
                                       "evidence_ref": request_ref}]
            result["success_conditions"] = ["The recorded effective values match the selected source facts"]
        else:
            result["parent_goal_ref"] = parent_goal_ref
        return result

    @staticmethod
    def make_issue(repository, number, context):
        body = f"{V2_START}\n{json.dumps(context, ensure_ascii=False)}\n{V2_END}"
        return {"repository": repository, "issue_number": number,
                "url": f"https://github.com/{repository}/issues/{number}", "body": body}


if __name__ == "__main__":
    unittest.main()
