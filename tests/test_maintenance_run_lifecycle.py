import unittest

from scripts import maintenance_audit as cli
from tools import maintenance_supply as ms
from tools.maintenance_ledger import (
    ActiveRun,
    extract_active_run,
    replace_active_run,
)


REPOSITORY = "o/r"
CONTROL_REF = "kinoko34077/devflow#1"
LEDGER_REF = "o/r#7"
RUN_ID = "audit:o/r:common.correctness:1"
CATALOG_DIGEST = "sha256:" + "e" * 64
FINGERPRINT = "sha256:" + "d" * 64


def active(depth="STANDARD", **overrides):
    value = dict(
        repository=REPOSITORY,
        run_id=RUN_ID,
        slot_id="common.correctness",
        generation=1,
        catalog_digest=CATALOG_DIGEST,
        fingerprint=FINGERPRINT,
        depth=depth,
        coverage_key="common.correctness",
        selected_at="2026-10-01T00:00:00Z",
        publisher_attempt_id="attempt-p5",
        score_breakdown=(("never_run", 40), ("unexecuted_lens", 15)),
    )
    value.update(overrides)
    return ActiveRun(**value)


def completion_result(**overrides):
    value = {
        "lens": "correctness",
        "result": "CLEAN",
        "findings_summary": "",
        "completed_at": "2026-10-01T00:30:00Z",
        "next_eligibility_reason": None,
        "evidence_refs": ("https://github.com/o/r/actions/runs/1",),
    }
    value.update(overrides)
    return value


def base_ledger_body(active_run=None):
    body = (
        "## Work Status\n\n"
        "`AUDITED`\n\n"
        "## Notes\n\n"
        "standing Ledger\n"
    )
    if active_run is None:
        return body
    return replace_active_run(body, active_run)[0]


def empty_control_body():
    return (
        "## Repository\n\n"
        "`o/r`\n\n"
        "## Repository State\n\n"
        "`ACTIVE`\n\n"
        "## Next Action\n\n"
        "`[IMPLEMENT]`\n\n"
        "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->\n"
        "{\n"
        '  "schema_version": 1,\n'
        '  "source_ref": "kinoko34077/devflow#1",\n'
        '  "repository": "o/r",\n'
        '  "candidates": []\n'
        "}\n"
        "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->\n\n"
        "<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_BEGIN -->\n"
        "{\n"
        '  "schema_version": "execution-portfolio-metadata.v1",\n'
        '  "source_ref": "kinoko34077/devflow#1",\n'
        '  "repository": "o/r",\n'
        '  "entries": []\n'
        "}\n"
        "<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_END -->\n"
    )


def published_control_body(ledger_body):
    selection = {
        "schema_version": "maintenance-selection.v1",
        "repository": REPOSITORY,
        "control_ref": CONTROL_REF,
        "ledger_ref": LEDGER_REF,
        "status": "SELECTED",
        "reason_code": "MAINTENANCE_SELECTED",
        "catalog_digest": CATALOG_DIGEST,
        "code_sha": "f" * 40,
        "selected": {
            "run_id": RUN_ID,
            "slot_id": "common.correctness",
            "generation": 1,
            "lens": "correctness",
            "depth": "STANDARD",
            "coverage_key": "common.correctness",
            "scope": {"kind": "repository", "selector": "."},
            "fingerprint": FINGERPRINT,
            "score": 55,
            "score_breakdown": [
                {"name": "never_run", "value": 40},
                {"name": "unexecuted_lens", "value": 15},
            ],
        },
    }
    ledger_snapshot = {
        "task_ref": LEDGER_REF,
        "repository": REPOSITORY,
        "body_sha256": cli.canonical_body_sha256(ledger_body),
        "state": "OPEN",
        "work_status": "READY_FOR_IMPLEMENTATION",
        "trusted": True,
        "is_pull_request": False,
        "entry_ref": "https://github.com/o/r/issues/7",
        "active_run": {
            "repository": REPOSITORY,
            "run_id": RUN_ID,
            "slot_id": "common.correctness",
            "generation": 1,
            "catalog_digest": CATALOG_DIGEST,
            "fingerprint": FINGERPRINT,
            "depth": "STANDARD",
            "coverage_key": "common.correctness",
            "publisher_attempt_id": "attempt-p5",
        },
    }
    control_snapshot = {
        "repository": REPOSITORY,
        "control_ref": CONTROL_REF,
        "repository_state": "ACTIVE",
        "trusted": True,
        "human_gate": False,
        "reviewer_gate": False,
        "external_wait": False,
        "security_gate": False,
        "observed_at": "2026-10-01T00:00:00Z",
        "fresh_until": "2026-10-01T01:00:00Z",
        "publisher_execution_attempt_id": "attempt-p5",
    }
    supply = ms.build_catalog_maintenance_candidate(
        selection,
        ledger_snapshot,
        control_snapshot,
    )
    body, changed = ms.reconcile_catalog_maintenance_projection_body(
        empty_control_body(),
        supply,
        task_ref=LEDGER_REF,
    )
    assert changed
    return body


class LifecyclePureTests(unittest.TestCase):
    def test_complete_run_builds_valid_record(self):
        from tools import maintenance_ledger as ml

        record = ml.complete_run(active(), completion_result())
        self.assertEqual(RUN_ID, record.run_id)
        self.assertEqual("CLEAN", record.result)
        self.assertEqual(("https://github.com/o/r/actions/runs/1",), record.evidence_refs)

    def test_finding_result_preserves_refs_without_creating_issue_semantics(self):
        from tools import maintenance_ledger as ml

        record = ml.complete_run(
            active(),
            completion_result(
                result="FINDINGS",
                findings_summary="P2 coverage gap; recorded only",
                evidence_refs=(
                    "https://github.com/o/r/issues/7#issuecomment-1",
                ),
            ),
        )
        self.assertEqual("FINDINGS", record.result)
        self.assertEqual(1, len(record.evidence_refs))
        self.assertNotIn("new_issue", record.__dict__)

    def test_deep_or_mutating_or_blocked_run_requires_promotion(self):
        from tools import maintenance_ledger as ml

        self.assertEqual(
            "PROMOTE_REQUIRED",
            ml.assess_run_continuation(active(depth="DEEP")),
        )
        for kwargs in (
            {"mutation_required": True},
            {"blocker": True},
            {"handoff_required": True},
            {"independent_acceptance": True},
            {"durable_finding": True},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(
                    "PROMOTE_REQUIRED",
                    ml.assess_run_continuation(active(), **kwargs),
                )

    def test_unchanged_volatile_state_resumes_without_replaying_accepted_checks(self):
        from tools import maintenance_ledger as ml

        assessment = ml.assess_active_run_for_resume(
            active(),
            current_fingerprint=FINGERPRINT,
            current_catalog_digest=CATALOG_DIGEST,
            volatile_evidence_complete=True,
        )
        self.assertEqual("RESUME", assessment.disposition)
        self.assertFalse(assessment.replay_completed_checks)
        self.assertEqual(RUN_ID, assessment.run_id)

    def test_drift_supersedes_and_missing_volatile_evidence_fails_closed(self):
        from tools import maintenance_ledger as ml

        drift = ml.assess_active_run_for_resume(
            active(),
            current_fingerprint="sha256:" + "9" * 64,
            current_catalog_digest=CATALOG_DIGEST,
            volatile_evidence_complete=True,
        )
        self.assertEqual("SUPERSEDE", drift.disposition)
        self.assertEqual("FINGERPRINT_DRIFT", drift.reason_code)

        missing = ml.assess_active_run_for_resume(
            active(),
            current_fingerprint=None,
            current_catalog_digest=CATALOG_DIGEST,
            volatile_evidence_complete=False,
        )
        self.assertEqual("NEEDS_EVIDENCE", missing.disposition)


class FakeTransport:
    def __init__(self, *, fail_control_withdrawal=False):
        self.ledger_body = base_ledger_body(active())
        self.control_body = published_control_body(self.ledger_body)
        self.comments = []
        self.fail_control_withdrawal = fail_control_withdrawal
        self.control_writes = 0
        self.ledger_writes = 0

    def get_issue(self, repository, number):
        if (repository, number) == ("o/r", 7):
            return {
                "number": 7,
                "state": "open",
                "title": "[MAINTENANCE] Audit Ledger",
                "body": self.ledger_body,
                "html_url": "https://github.com/o/r/issues/7",
                "author_association": "OWNER",
            }
        if (repository, number) == ("kinoko34077/devflow", 1):
            return {
                "number": 1,
                "state": "open",
                "title": "[REPO] r",
                "body": self.control_body,
                "author_association": "OWNER",
            }
        raise AssertionError((repository, number))

    def list_issue_comments(self, repository, number):
        if (repository, number) != ("o/r", 7):
            raise AssertionError((repository, number))
        return list(self.comments)

    def post_issue_comment(self, repository, number, body):
        if (repository, number) != ("o/r", 7):
            raise AssertionError((repository, number))
        self.comments.append({
            "body": body,
            "author_association": "OWNER",
        })
        return True

    def update_issue_body(
        self,
        repository,
        number,
        expected_body_sha256,
        body,
    ):
        if (repository, number) != ("o/r", 7):
            raise AssertionError((repository, number))
        if cli.canonical_body_sha256(self.ledger_body) != expected_body_sha256:
            return False
        self.ledger_writes += 1
        self.ledger_body = body
        return True

    def update_control_body(
        self,
        repository,
        control_ref,
        expected_body_sha256,
        body,
    ):
        if cli.canonical_body_sha256(self.control_body) != expected_body_sha256:
            return False
        if self.fail_control_withdrawal:
            return False
        self.control_writes += 1
        self.control_body = body
        return True

    def get_control(self, repository, control_ref):
        return {
            "repository": repository,
            "control_ref": control_ref,
            "body": self.control_body,
        }

    def post_supply_transition(self, body):
        return True


class LifecycleWriteTests(unittest.TestCase):
    def test_lightweight_completion_records_comment_clears_run_and_withdraws_candidate(self):
        transport = FakeTransport()
        payload = cli.execute_maintenance_completion(
            transport,
            repository=REPOSITORY,
            control_ref=CONTROL_REF,
            ledger_ref=LEDGER_REF,
            run_id=RUN_ID,
            result=completion_result(),
            attempt_id="attempt-complete",
            apply=True,
        )
        self.assertTrue(payload["applied"])
        self.assertFalse(payload["reconciliation_required"])
        self.assertEqual(1, len(transport.comments))
        self.assertIsNone(extract_active_run(transport.ledger_body, REPOSITORY))
        self.assertEqual("AUDITED", cli.ledger_work_status(transport.ledger_body))
        self.assertNotIn('"task": "o/r#7"', transport.control_body)

    def test_completion_is_idempotent_for_same_run_id(self):
        transport = FakeTransport()
        first = cli.execute_maintenance_completion(
            transport,
            repository=REPOSITORY,
            control_ref=CONTROL_REF,
            ledger_ref=LEDGER_REF,
            run_id=RUN_ID,
            result=completion_result(),
            attempt_id="attempt-complete",
            apply=True,
        )
        second = cli.execute_maintenance_completion(
            transport,
            repository=REPOSITORY,
            control_ref=CONTROL_REF,
            ledger_ref=LEDGER_REF,
            run_id=RUN_ID,
            result=completion_result(),
            attempt_id="attempt-complete-2",
            apply=True,
        )
        self.assertTrue(first["applied"])
        self.assertTrue(second["already_completed"])
        self.assertEqual(1, len(transport.comments))
        self.assertEqual(1, transport.ledger_writes)

    def test_control_withdrawal_failure_preserves_completed_history_and_requires_reconciliation(self):
        transport = FakeTransport(fail_control_withdrawal=True)
        payload = cli.execute_maintenance_completion(
            transport,
            repository=REPOSITORY,
            control_ref=CONTROL_REF,
            ledger_ref=LEDGER_REF,
            run_id=RUN_ID,
            result=completion_result(),
            attempt_id="attempt-complete",
            apply=True,
        )
        self.assertTrue(payload["applied"])
        self.assertTrue(payload["reconciliation_required"])
        self.assertEqual(
            "CONTROL_WITHDRAWAL_FAILED_AFTER_COMPLETION",
            payload["reason_code"],
        )
        self.assertEqual(1, len(transport.comments))
        self.assertIsNone(extract_active_run(transport.ledger_body, REPOSITORY))
        self.assertIn('"task": "o/r#7"', transport.control_body)

    def test_interrupted_active_run_is_not_replaced_by_another_slot(self):
        transport = FakeTransport()
        wrong = "audit:o/r:common.security:1"
        with self.assertRaisesRegex(
            ms.MaintenanceSupplyError,
            "run_id",
        ):
            cli.execute_maintenance_completion(
                transport,
                repository=REPOSITORY,
                control_ref=CONTROL_REF,
                ledger_ref=LEDGER_REF,
                run_id=wrong,
                result=completion_result(),
                attempt_id="attempt-wrong",
                apply=True,
            )
        current = extract_active_run(transport.ledger_body, REPOSITORY)
        self.assertEqual(RUN_ID, current.run_id)
        self.assertEqual(0, len(transport.comments))


if __name__ == "__main__":
    unittest.main()
