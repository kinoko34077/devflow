import unittest

try:
    from tools import maintenance_supply as ms
except ImportError:
    ms = None

try:
    from tools.maintenance_triage import TriageDecision
except ImportError:
    TriageDecision = None


BODY_SHA = "sha256:" + "a" * 64
OTHER_SHA = "sha256:" + "b" * 64


def decision(**overrides):
    value = {
        "action": "PUBLISH_EXISTING_OWNER",
        "report_id": "sha256:" + "c" * 64,
        "disposition": "AUTO_ADVANCE",
        "work_class": "sync-check",
        "owner_ref": "o/r#7",
        "reason_codes": ("EXACT_EXISTING_OWNER",),
    }
    value.update(overrides)
    if TriageDecision is None:
        return value
    return TriageDecision(**value)


def owner(**overrides):
    value = {
        "task_ref": "o/r#7",
        "repository": "o/r",
        "body_sha256": BODY_SHA,
        "state": "OPEN",
        "work_status": "READY_FOR_IMPLEMENTATION",
        "scope_ready": True,
        "blocked": False,
        "requires_user_confirmation": False,
        "conflict_keys": ("component:o/r:maintenance",),
        "trusted": True,
        "is_pull_request": False,
        "entry_ref": "https://github.com/o/r/issues/7",
        "human_gate": False,
        "reviewer_gate": False,
        "external_wait": False,
        "security_gate": False,
    }
    value.update(overrides)
    return value


def control(**overrides):
    value = {
        "repository": "o/r",
        "control_ref": "kinoko34077/devflow#1",
        "repository_state": "ACTIVE",
        "trusted": True,
        "human_gate": False,
        "external_wait": False,
        "observed_at": "2026-10-01T00:00:00Z",
        "fresh_until": "2026-10-01T01:00:00Z",
        "publisher_execution_attempt_id": "attempt-p5",
    }
    value.update(overrides)
    return value


class MaintenanceSupplyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            ms,
            "maintenance_supply module must exist",
        )

    def test_existing_exact_owner_builds_sync_check_supply(self):
        supply = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(),
        )
        self.assertIsNotNone(supply)
        self.assertEqual(
            supply["admission"]["task"],
            "o/r#7",
        )
        self.assertEqual(
            supply["admission"]["task_body_sha256"],
            BODY_SHA,
        )
        self.assertEqual(
            supply["admission"]["roles"],
            [{"role": "implementer", "next_action_tag": "IMPLEMENT"}],
        )
        self.assertEqual(
            supply["portfolio"]["work_class"],
            "sync-check",
        )
        self.assertEqual(
            supply["portfolio"]["task_body_sha256"],
            BODY_SHA,
        )
        self.assertEqual(
            supply["publisher_execution_attempt_id"],
            "attempt-p5",
        )
        self.assertTrue(
            supply["candidate_fingerprint"].startswith("sha256:")
        )

    def test_no_existing_owner_never_creates_supply(self):
        self.assertIsNone(
            ms.build_existing_owner_candidate(
                decision(owner_ref=None),
                owner(),
                control(),
            )
        )

    def test_owner_identity_digest_and_ready_state_are_strict(self):
        cases = (
            owner(task_ref="o/r#8"),
            owner(body_sha256=OTHER_SHA),
            owner(state="CLOSED"),
            owner(work_status="IMPLEMENTING"),
            owner(scope_ready=False),
            owner(blocked=True),
            owner(trusted=False),
            owner(is_pull_request=True),
        )
        for snapshot in cases:
            with self.subTest(snapshot=snapshot):
                self.assertIsNone(
                    ms.build_existing_owner_candidate(
                        decision(),
                        snapshot,
                        control(
                            expected_owner_body_sha256=BODY_SHA,
                        ),
                    )
                )

    def test_any_stronger_gate_suppresses_supply(self):
        for field in (
            "human_gate",
            "reviewer_gate",
            "external_wait",
            "security_gate",
        ):
            with self.subTest(field=field):
                self.assertIsNone(
                    ms.build_existing_owner_candidate(
                        decision(),
                        owner(**{field: True}),
                        control(),
                    )
                )

    def test_same_evidence_has_stable_identity(self):
        first = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(observed_at="2026-10-01T00:00:00Z"),
        )
        second = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(observed_at="2026-10-01T00:10:00Z"),
        )
        self.assertEqual(
            first["candidate_fingerprint"],
            second["candidate_fingerprint"],
        )
        reconciled = ms.reconcile_existing_owner_supply(
            [first],
            first,
        )
        self.assertEqual(reconciled["active"], [first])
        self.assertEqual(reconciled["superseded_ids"], [])

    def test_owner_readiness_or_freshness_change_withdraws_old_supply(self):
        existing = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(),
        )
        desired = ms.build_existing_owner_candidate(
            decision(),
            owner(work_status="IMPLEMENTING"),
            control(),
        )
        self.assertIsNone(desired)
        reconciled = ms.reconcile_existing_owner_supply(
            [existing],
            desired,
            task_ref="o/r#7",
        )
        self.assertEqual(reconciled["active"], [])
        self.assertEqual(
            reconciled["superseded_ids"],
            [existing["publication_id"]],
        )

    def test_publisher_attempt_cannot_consume_its_own_change(self):
        supply = ms.build_existing_owner_candidate(
            decision(),
            owner(),
            control(
                publisher_execution_attempt_id="attempt-p5",
            ),
        )
        self.assertTrue(
            ms.published_by_attempt(
                supply,
                "attempt-p5",
            )
        )
        self.assertFalse(
            ms.published_by_attempt(
                supply,
                "later-attempt",
            )
        )


if __name__ == "__main__":
    unittest.main()
