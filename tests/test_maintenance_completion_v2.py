"""Native maintenance v2 completion opt-in negative and replay contracts."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import maintenance_audit as cli
from tests.test_maintenance_run_lifecycle import (
    CATALOG_DIGEST, FINGERPRINT, RUN_ID, CONTROL_REF, LEDGER_REF,
    REPOSITORY, FakeTransport, active, completion_result,
)
from tools.maintenance_catalog import ResolvedSlot, Scope
from tools.maintenance_completion_v2 import prepare_v2_completion
from tools.maintenance_ledger import complete_run, extract_active_run
from tools.maintenance_run_attestation import (
    AttestedRun, RunAttestationError, parse_attested_run_comment,
    render_attested_run_comment,
)


def known_slot():
    return ResolvedSlot(
        repository=REPOSITORY, slot_id="common.correctness",
        title="Correctness", lifecycle="ACTIVE",
        scope=Scope("repository", "."), lens="correctness",
        coverage_key="common.correctness", risk="MEDIUM",
        cadence_class="GENERAL", minimum_depth="STANDARD",
        external_freshness_class="NORMAL", description="test", source="common",
    )


def prepared_v2_comment():
    return render_attested_run_comment(AttestedRun(
        complete_run(active(), completion_result()),
        Scope("repository", "."), "common.correctness", CATALOG_DIGEST,
    ))


def execute(transport, *, apply=True, attempt="attempt-complete", version="v2"):
    return cli.execute_maintenance_completion(
        transport, repository=REPOSITORY, control_ref=CONTROL_REF,
        ledger_ref=LEDGER_REF, run_id=RUN_ID,
        result=completion_result(), attempt_id=attempt, apply=apply,
        record_format=version,
    )


class V2PureSourcePreflightTests(unittest.TestCase):
    def prepare(self, *, drift=False, rollout="PILOT", head_drift=False):
        act = active()
        result = complete_run(act, completion_result())
        with (
            patch("tools.maintenance_completion_v2._catalog_bundle") as bundle,
            patch("tools.maintenance_completion_v2._default_head") as head,
            patch("tools.maintenance_completion_v2.canonical_catalog_digest") as digest,
            patch("tools.maintenance_completion_v2.build_maintenance_fingerprint") as fingerprint,
        ):
            bundle.return_value = (
                object(), SimpleNamespace(rollout=rollout), (known_slot(),),
                "sha256:" + ("f"*64 if drift else "e"*64), "a"*40,
                {}, {},
            )
            head.return_value = "b"*40 if head_drift else "a"*40
            digest.return_value = CATALOG_DIGEST
            fingerprint.return_value = FINGERPRINT
            return prepare_v2_completion(object(), act, result,
                                         completion_attempt_id="attempt-complete")

    def test_valid_preflight_binds_exact_active_run_and_scope(self):
        proof = parse_attested_run_comment(self.prepare())
        self.assertEqual(RUN_ID, proof.record.run_id)
        self.assertEqual(CATALOG_DIGEST, proof.catalog_digest)
        self.assertEqual(Scope("repository", "."), proof.scope)

    def test_source_catalog_or_rolling_head_drift_fails_before_write(self):
        for options in ({"drift": True}, {"head_drift": True}, {"rollout": "DISABLED"}):
            with self.subTest(options=options), self.assertRaises(RunAttestationError):
                self.prepare(**options)

    def test_same_attempt_as_publisher_is_forbidden(self):
        act = active()
        record = complete_run(act, completion_result())
        with self.assertRaisesRegex(RunAttestationError, "publisher attempt"):
            prepare_v2_completion(object(), act, record,
                                  completion_attempt_id=act.publisher_attempt_id)


class V2IntegrationWriteTests(unittest.TestCase):
    def test_v2_native_comment_then_readback_clear_and_retry_no_duplicate(self):
        transport = FakeTransport()
        with patch.object(cli, "prepare_v2_completion", return_value=prepared_v2_comment()):
            first = execute(transport)
        self.assertTrue(first["applied"])
        self.assertFalse(first["reconciliation_required"])
        self.assertEqual(1, len(transport.comments))
        self.assertIn("devflow-maintenance-run:v2", transport.comments[0]["body"])
        self.assertIsNone(extract_active_run(transport.ledger_body, REPOSITORY))
        replay = execute(transport, attempt="attempt-later")
        self.assertTrue(replay["already_completed"])
        self.assertEqual(1, len(transport.comments))
        self.assertEqual(1, transport.ledger_writes)

    def test_default_v1_workflow_remains_unchanged(self):
        transport = FakeTransport()
        result = execute(transport, version="v1")
        self.assertTrue(result["applied"])
        self.assertIn("devflow-maintenance-run:v1", transport.comments[0]["body"])

    def test_attestation_failure_cannot_publish_or_clear(self):
        transport = FakeTransport()
        with patch.object(cli, "prepare_v2_completion", side_effect=RunAttestationError("stale")):
            with self.assertRaisesRegex(RunAttestationError, "stale"):
                execute(transport)
        self.assertEqual([], transport.comments)
        self.assertEqual(0, transport.ledger_writes)
        self.assertIsNotNone(extract_active_run(transport.ledger_body, REPOSITORY))

    def test_readback_not_visible_keeps_active_run_and_explicit_recovery(self):
        class Invisible(FakeTransport):
            def list_issue_comments(self, repository, number):
                return []
        transport = Invisible()
        with patch.object(cli, "prepare_v2_completion", return_value=prepared_v2_comment()):
            value = execute(transport)
        self.assertTrue(value["reconciliation_required"])
        self.assertEqual("V2_COMMENT_READBACK_UNCONFIRMED", value["reason_code"])
        self.assertIsNotNone(extract_active_run(transport.ledger_body, REPOSITORY))
        self.assertEqual(0, transport.ledger_writes)

    def test_unknown_version_rejects_before_side_effect(self):
        transport = FakeTransport()
        with self.assertRaisesRegex(Exception, "unknown maintenance record format"):
            execute(transport, version="v999")
        self.assertEqual([], transport.comments)

    def test_duplicate_same_run_id_conflicting_trusted_v1_v2_refuses_replay(self):
        transport = FakeTransport()
        with patch.object(cli, "prepare_v2_completion", return_value=prepared_v2_comment()):
            execute(transport)
        transport.comments.append({
            "body": prepared_v2_comment(),
            "author_association": "OWNER",
            "user": {"id": 79015263, "login": "kinoko34077"},
        })
        with self.assertRaisesRegex(Exception, "duplicate trusted Ledger run ID"):
            execute(transport, attempt="attempt-next")

    def test_v2_dry_run_has_zero_posts_and_preserves_active_run(self):
        transport = FakeTransport()
        with patch.object(cli, "prepare_v2_completion", return_value=prepared_v2_comment()):
            result = execute(transport, apply=False)
        self.assertFalse(result["applied"])
        self.assertEqual([], transport.comments)
        self.assertEqual(0, transport.ledger_writes)


if __name__ == "__main__":
    unittest.main()
