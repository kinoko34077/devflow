from datetime import datetime, timedelta, timezone
import unittest

from tools.ci_verification_plan import (
    Decision, Observation, Requirement, assess_verification,
)


NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)
REPO = "kinoko34077/testapp"


def code(**changes):
    identity = {
        "tree": "tree-a", "recipe": "npm-test-v1",
        "environment": "ubuntu/node22", "dependencies": "lock-a",
    }
    identity.update(changes)
    return Requirement(REPO, "unit-tests", identity)


def evidence(requirement=None, outcome="success", ref="run/42/job/1",
             valid_until=None):
    return Observation(requirement or code(), outcome, ref, valid_until)


class CIVerificationPlanTests(unittest.TestCase):
    def assess(self, required, *observations):
        return assess_verification(required, observations, now=NOW)

    def test_equivalent_candidate_across_pr_and_main(self):
        # The trusted collector resolves actual trees and relevant inputs.
        # The two commits need not have the same commit SHA or event name.
        self.assertEqual(
            self.assess(code(), evidence(code())),
            Decision("REUSE_CANDIDATE", "EQUIVALENT_SUCCESS", ("run/42/job/1",)),
        )

    def test_any_relevant_input_change_requires_verification(self):
        for field in ("tree", "recipe", "environment", "dependencies"):
            with self.subTest(field=field):
                self.assertEqual(self.assess(code(**{field: "changed"}),
                                             evidence()).action, "RUN")

    def test_pr_metadata_independent_of_code(self):
        old = Requirement(REPO, "owner-metadata", {"body": "old", "validator": "v1"})
        new = Requirement(REPO, "owner-metadata", {"body": "new", "validator": "v1"})
        observations = (evidence(), evidence(old, ref="metadata/1"))
        self.assertEqual(self.assess(code(), *observations).action, "REUSE_CANDIDATE")
        self.assertEqual(self.assess(new, *observations).action, "RUN")

    def test_repository_and_guarantee_do_not_cross(self):
        for required in (
            Requirement("other/repo", "unit-tests", code().identity),
            Requirement(REPO, "deployment", code().identity),
        ):
            self.assertEqual(self.assess(required, evidence()).action, "RUN")

    def test_bad_current_results_never_reused(self):
        for outcome in ("failure", "cancelled", "skipped", "neutral", "unknown",
                        "timed_out", "action_required", ""):
            with self.subTest(outcome=outcome):
                self.assertEqual(self.assess(code(), evidence(outcome=outcome)).action,
                                 "RUN")

    def test_conflicting_current_observations_not_reused(self):
        self.assertEqual(self.assess(code(), evidence(),
                                     evidence(outcome="failure", ref="run/43")).action,
                         "RUN")

    def test_active_equivalent_run_is_wait_not_success(self):
        for outcome in ("queued", "in_progress"):
            self.assertEqual(self.assess(code(), evidence(outcome=outcome)).action,
                             "WAIT")
            self.assertEqual(self.assess(code(), evidence(),
                                         evidence(outcome=outcome, ref="run/43")).action,
                             "WAIT")
        self.assertEqual(self.assess(code(), evidence(code(tree="older"),
                                                     outcome="in_progress")).action,
                         "RUN")

    def test_freshness_boundary_and_unknown_time(self):
        for expires in (NOW, NOW - timedelta(seconds=1), NOW.replace(tzinfo=None)):
            self.assertEqual(self.assess(code(), evidence(valid_until=expires)).action,
                             "RUN")
        self.assertEqual(self.assess(code(), evidence(valid_until=NOW + timedelta(seconds=1))).action,
                         "REUSE_CANDIDATE")

    def test_missing_identity_never_matches(self):
        for identity in ({}, {"tree": ""}, {"tree": None}):
            self.assertEqual(self.assess(Requirement(REPO, "unit-tests", identity)).action,
                             "HOLD")
        self.assertEqual(self.assess(code(), evidence(Requirement(
            REPO, "unit-tests", {"tree": "tree-a"}))).action, "RUN")
        self.assertEqual(assess_verification(code(), (), now=NOW.replace(tzinfo=None)).action,
                         "HOLD")

    def test_missing_reference_and_empty_observations(self):
        self.assertEqual(self.assess(code(), evidence(ref="")).action, "RUN")
        self.assertEqual(self.assess(code()).action, "RUN")

    def test_evidence_order_and_duplicate_refs_do_not_affect_decision(self):
        a, b = evidence(ref="b"), evidence(ref="a")
        self.assertEqual(self.assess(code(), a, b, a), self.assess(code(), b, a))
        self.assertEqual(self.assess(code(), a, b).evidence_refs, ("a", "b"))


if __name__ == "__main__":
    unittest.main()
