import unittest

try:
    from tools import development_reconciler as dr
except ImportError:
    dr = None


HEAD = "a" * 40
OTHER = "b" * 40


def base(**overrides):
    data = dict(
        task_ref="o/r#1",
        task_kind="FINITE",
        task_open=True,
        acceptance_satisfied=True,
        pr_number=7,
        pr_state="OPEN",
        pr_head_sha=HEAD,
        expected_head_sha=HEAD,
        checks="PASS",
        formal_review="PASS",
        different_reviewer_required=False,
        different_reviewer="MISSING",
        request_changes=False,
        blocking_finding=False,
        owning_blocker=False,
        human_gate=False,
        external_wait=False,
        mergeable=True,
        revertible=True,
        current_state_changed=False,
        control_changed=False,
        evidence_complete=True,
    )
    data.update(overrides)
    return data


class ReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(dr, "development_reconciler module must exist")

    def test_safe_open_pr_auto_advances(self):
        decision = dr.evaluate_pr(base())
        self.assertEqual(
            (decision.disposition, decision.transition),
            ("AUTO_ADVANCE", "MERGE_PR"),
        )

    def test_pending_checks_wait_external(self):
        decision = dr.evaluate_pr(base(checks="PENDING"))
        self.assertEqual(decision.disposition, "WAIT_EXTERNAL")

    def test_failed_checks_do_not_advance(self):
        decision = dr.evaluate_pr(base(checks="FAIL"))
        self.assertEqual(decision.disposition, "NO_ACTION")

    def test_stale_review_needs_evidence(self):
        decision = dr.evaluate_pr(base(formal_review="STALE"))
        self.assertEqual(decision.disposition, "NEEDS_EVIDENCE")

    def test_evaluator_rejects_expected_head_mismatch(self):
        decision = dr.evaluate_pr(base(expected_head_sha=OTHER))
        self.assertEqual(decision.disposition, "NEEDS_EVIDENCE")

    def test_incomplete_evidence_fails_closed(self):
        decision = dr.evaluate_pr(base(evidence_complete=False))
        self.assertEqual(decision.disposition, "NEEDS_EVIDENCE")

    def test_different_reviewer_gate(self):
        decision = dr.evaluate_pr(
            base(different_reviewer_required=True, different_reviewer="MISSING")
        )
        self.assertEqual(decision.disposition, "NEEDS_REVIEWER")

    def test_human_gate_preempts_merge(self):
        decision = dr.evaluate_pr(base(human_gate=True))
        self.assertEqual(decision.disposition, "NEEDS_HUMAN")

    def test_request_changes_blocks(self):
        decision = dr.evaluate_pr(base(request_changes=True))
        self.assertEqual(decision.disposition, "NO_ACTION")

    def test_blocking_finding_blocks(self):
        decision = dr.evaluate_pr(base(blocking_finding=True))
        self.assertEqual(decision.disposition, "NO_ACTION")

    def test_owning_task_blocker_blocks(self):
        decision = dr.evaluate_pr(base(owning_blocker=True))
        self.assertEqual(decision.disposition, "NO_ACTION")

    def test_merged_finite_task_reconciles(self):
        decision = dr.evaluate_pr(base(pr_state="MERGED", current_state_changed=True))
        self.assertEqual(decision.transition, "POST_MERGE_RECONCILE")
        self.assertIn("CLOSE_OWNING_TASK", decision.actions)
        self.assertIn("UPDATE_CURRENT_STATE", decision.actions)

    def test_repository_control_never_closes(self):
        decision = dr.evaluate_pr(
            base(
                task_kind="REPOSITORY_CONTROL",
                pr_state="MERGED",
                control_changed=True,
            )
        )
        self.assertNotIn("CLOSE_OWNING_TASK", decision.actions)
        self.assertIn("UPDATE_CONTROL", decision.actions)

    def test_merge_executor_guards_head_and_is_idempotent(self):
        class Transport:
            def __init__(self):
                self.merges = 0
                self.pr = {"state": "open", "head_sha": HEAD, "merged": False}

            def get_pr(self, repo, number):
                return dict(self.pr)

            def merge_pr(self, repo, number, expected):
                self.assert_expected = expected
                self.merges += 1
                self.pr = {"state": "closed", "head_sha": HEAD, "merged": True}
                return True

        transport = Transport()
        decision = dr.evaluate_pr(base())
        result = dr.execute_merge(decision, transport, "o/r")
        self.assertTrue(result.applied)
        self.assertEqual(transport.merges, 1)
        self.assertEqual(transport.assert_expected, HEAD)

        repeated = dr.execute_merge(decision, transport, "o/r")
        self.assertTrue(repeated.already_applied)
        self.assertEqual(transport.merges, 1)

    def test_merge_executor_refuses_head_move(self):
        class Transport:
            def get_pr(self, repo, number):
                return {"state": "open", "head_sha": OTHER, "merged": False}

            def merge_pr(self, *args):
                raise AssertionError("must not merge")

        result = dr.execute_merge(dr.evaluate_pr(base()), Transport(), "o/r")
        self.assertFalse(result.applied)
        self.assertEqual(result.disposition, "NEEDS_EVIDENCE")

    def test_post_merge_executor_is_ownership_sensitive_and_idempotent(self):
        class Transport:
            def __init__(self):
                self.closed = False
                self.current_state_updates = 0
                self.control_updates = 0

            def close_task(self, task_ref):
                if self.closed:
                    return False
                self.closed = True
                return True

            def update_current_state(self, task_ref):
                if self.current_state_updates:
                    return False
                self.current_state_updates += 1
                return True

            def update_control(self, task_ref):
                if self.control_updates:
                    return False
                self.control_updates += 1
                return True

        transport = Transport()
        decision = dr.evaluate_pr(
            base(
                pr_state="MERGED",
                current_state_changed=True,
                control_changed=True,
            )
        )
        result = dr.execute_post_merge(decision, transport)
        self.assertTrue(result.applied)
        self.assertTrue(transport.closed)
        self.assertEqual(transport.current_state_updates, 1)
        self.assertEqual(transport.control_updates, 1)

        repeated = dr.execute_post_merge(decision, transport)
        self.assertTrue(repeated.already_applied)
        self.assertEqual(transport.current_state_updates, 1)
        self.assertEqual(transport.control_updates, 1)


if __name__ == "__main__":
    unittest.main()
