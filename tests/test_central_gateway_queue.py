from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace

from tools.central_execution_gateway import Job, Record, Receipt, request_digest
from tools.central_gateway_queue import LedgerDenied, SQLiteFakeJobLedger


class DurableFakeJobLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "ledger.db")
        self.first = SQLiteFakeJobLedger(self.db_path)
        self.addCleanup(self.first.close)
        self.job = Job(
            "kinoko34077/test-app", "kinoko34077/devflow#541",
            "b" * 40, "audit.read", "a" * 64, "attempt-1",
            {"secret_like_input": "never-store-this-sensitive-plaintext"},
        )
        self.digest = request_digest(self.job)
        self.rec = Record(
            self.job, "central-chat", "nonce-1", 200, self.digest, 9, "QUEUED",
        )
        self.receipt = Receipt(
            self.digest, "external_isolated", 9, "f" * 64, simulated=True,
        )

    def denies(self, reason, action):
        with self.assertRaises(LedgerDenied) as ctx:
            action()
        self.assertEqual(str(ctx.exception), reason)

    def second_handle(self):
        second = SQLiteFakeJobLedger(self.db_path)
        self.addCleanup(second.close)
        return second

    def test_queued_to_inflight_to_fake_result(self):
        row = self.first.admit_fake(self.rec)
        self.assertEqual((row.state, row.actor, row.epoch),
                         ("QUEUED", "central-chat", 9))
        started = self.first.begin_fake(
            self.digest, epoch=9, backend="external_isolated",
        )
        self.assertEqual(started.state, "IN_FLIGHT")
        done = self.first.complete_fake(self.receipt)
        self.assertEqual((done.state, done.output_sha256),
                         ("SIMULATED_RESULT", "f" * 64))
        self.assertEqual(self.first.complete_fake(self.receipt), done)
        self.denies("ALREADY_DISPATCHED", lambda: self.first.begin_fake(
            self.digest, epoch=9, backend="external_isolated",
        ))

    def test_duplicate_submission_never_requeues_finished_job(self):
        self.first.admit_fake(self.rec)
        self.first.begin_fake(self.digest, epoch=9, backend="external_isolated")
        self.first.complete_fake(self.receipt)
        self.assertEqual(self.first.admit_fake(self.rec).state, "SIMULATED_RESULT")

    def test_crash_reopen_in_flight_requires_manual_reconciliation(self):
        self.first.admit_fake(self.rec)
        self.first.begin_fake(self.digest, epoch=9, backend="github_actions")
        restart = self.second_handle()
        self.assertEqual(restart.observe(self.digest).state, "IN_FLIGHT")
        self.denies("ALREADY_DISPATCHED", lambda: restart.begin_fake(
            self.digest, epoch=9, backend="github_actions",
        ))
        row = restart.mark_uncertain(self.digest, epoch=9)
        self.assertEqual(row.state, "UNCERTAIN")
        self.assertEqual(restart.mark_uncertain(self.digest, epoch=9), row)
        self.denies("ALREADY_DISPATCHED", lambda: restart.begin_fake(
            self.digest, epoch=9, backend="github_actions",
        ))
        self.assertEqual(self.first.admit_fake(self.rec).state, "UNCERTAIN")

    def test_two_connections_cannot_begin_same_attempt_twice(self):
        other = self.second_handle()
        other.admit_fake(self.rec)
        self.assertEqual(
            self.first.begin_fake(self.digest, epoch=9, backend="external_isolated").state,
            "IN_FLIGHT",
        )
        self.denies("ALREADY_DISPATCHED", lambda: other.begin_fake(
            self.digest, epoch=9, backend="external_isolated",
        ))

    def test_stale_epoch_never_claims_or_completes(self):
        self.first.admit_fake(self.rec)
        self.denies("STALE_FENCE_EPOCH", lambda: self.first.begin_fake(
            self.digest, epoch=8, backend="github_actions",
        ))
        self.first.begin_fake(self.digest, epoch=9, backend="github_actions")
        self.denies("STALE_FENCE_EPOCH", lambda: self.first.complete_fake(
            replace(self.receipt, fence_epoch=10, backend="github_actions"),
        ))

    def test_invalid_receipt_rejected(self):
        self.first.admit_fake(self.rec)
        self.first.begin_fake(self.digest, epoch=9, backend="github_actions")
        invalid = (
            replace(self.receipt, simulated=False),
            replace(self.receipt, backend="unknown"),
            replace(self.receipt, output_sha256="incorrect"),
            replace(self.receipt, fence_epoch=True),
            replace(self.receipt, request_digest="bad"),
        )
        for item in invalid:
            with self.subTest(item=item):
                self.denies("INVALID_FAKE_RECEIPT",
                            lambda item=item: self.first.complete_fake(item))
        self.denies("BACKEND_MISMATCH", lambda: self.first.complete_fake(self.receipt))
        okay = replace(self.receipt, backend="github_actions")
        self.first.complete_fake(okay)
        self.denies("RESULT_COLLISION", lambda: self.first.complete_fake(
            replace(okay, output_sha256="0" * 64),
        ))

    def test_inflight_and_terminal_states_cannot_be_retroactively_admitted(self):
        for state in ("IN_FLIGHT", "UNCERTAIN", "SIMULATED_RESULT"):
            self.denies("NOT_A_FAKE_QUEUED_RECORD", lambda state=state:
                        self.first.admit_fake(replace(self.rec, state=state)))

    def test_nonce_replay_cross_attempt_and_cross_actor_collision(self):
        self.first.admit_fake(self.rec)
        other_job = replace(self.job, attempt_id="attempt-2")
        other = replace(self.rec, job=other_job, digest=request_digest(other_job))
        self.denies("NONCE_REPLAY", lambda: self.first.admit_fake(other))
        same_attempt_other_actor = replace(
            self.rec, actor="another-actor",
        )
        self.denies("ATTEMPT_COLLISION",
                    lambda: self.first.admit_fake(same_attempt_other_actor))

    def test_unserializable_fake_record_fails_closed(self):
        for bad_job in (
            replace(self.job, inputs={"bad": object()}),
            replace(self.job, inputs=[]),
        ):
            with self.subTest(job=repr(bad_job)[:80]):
                self.denies("INVALID_FAKE_RECORD", lambda b=bad_job:
                            self.first.admit_fake(replace(self.rec, job=b)))

    def test_wrong_job_digest_and_epoch_zero_rejected(self):
        self.denies("INVALID_FAKE_RECORD", lambda: self.first.admit_fake(
            replace(self.rec, digest="c" * 64),
        ))
        self.denies("INVALID_FAKE_RECORD", lambda: self.first.admit_fake(
            replace(self.rec, epoch=0),
        ))

    def test_local_db_never_persists_inputs_tokens_or_source_body(self):
        self.first.admit_fake(self.rec)
        self.first.close()
        with open(self.db_path, "rb") as db_file:
            data = db_file.read()
        self.assertNotIn(b"never-store-this-sensitive-plaintext", data)
        self.assertIn(self.digest.encode("ascii"), data)
        # Close can be called repeatedly without mutating any queued row.
        reopened = self.second_handle()
        self.assertEqual(reopened.observe(self.digest).state, "QUEUED")

    def test_full_capacity_fails_closed_without_eviction(self):
        for i in range(64):
            job = replace(self.job, attempt_id=f"attempt-{i}")
            dig = request_digest(job)
            self.first.admit_fake(Record(
                job, "central-chat", f"nonce-{i}", 200, dig, 9, "QUEUED",
            ))
        job = replace(self.job, attempt_id="attempt-last")
        self.denies("LEDGER_CAPACITY", lambda: self.first.admit_fake(
            Record(job, "central-chat", "nonce-last", 200, request_digest(job), 9, "QUEUED")
        ))

    def test_invalid_lookup_begin_and_uncertain_without_dispatch(self):
        self.denies("INVALID_DIGEST", lambda: self.first.observe("main"))
        self.denies("INVALID_BEGIN", lambda: self.first.begin_fake(
            self.digest, epoch=True, backend="github_actions"))
        self.denies("UNKNOWN_ATTEMPT", lambda: self.first.begin_fake(
            self.digest, epoch=9, backend="github_actions"))
        self.first.admit_fake(self.rec)
        self.denies("NOT_IN_FLIGHT", lambda: self.first.mark_uncertain(
            self.digest, epoch=9))
        self.denies("NOT_IN_FLIGHT", lambda: self.first.complete_fake(
            self.receipt))

    def test_backend_binding_does_not_elevate_claim_or_run_anything(self):
        self.first.admit_fake(self.rec)
        row = self.first.begin_fake(
            self.digest, epoch=9, backend="github_actions",
        )
        self.assertEqual(row.state, "IN_FLIGHT")
        self.assertNotIn("secret_like_input", repr(row))
        self.assertEqual(row.output_sha256, None)


if __name__ == "__main__":
    unittest.main()
