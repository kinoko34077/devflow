"""Test-only C2 integrated fake ingress->SQLite CAS->FakeBackend evidence."""
from __future__ import annotations

import hashlib
import hmac
import os
import tempfile
import unittest
from dataclasses import replace

from tools.central_execution_gateway import (
    ClaimView, FakeBackend, FakeClaims, FakeHealth, Job, MemoryStore,
    OfflineGateway, RecipePolicy, SignedIngress, Receipt,
    request_digest, signing_payload,
)
from tools.central_gateway_queue import SQLiteFakeJobLedger
from tools.central_gateway_fake_dispatch import (
    FakeBudget, FakeDispatchDenied, FakeIntegratedDispatch,
    SignedTestPrincipal, TestPrincipalIssuer,
)


class FakeIntegratedDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "fake-jobs.sqlite3")
        self.auth_key = b"F2C-separate-injected-only-test-key-32-bytes"
        self.issuer_key = b"F2C-issuer-fake-not-GitHub-OIDC-KEY-32"
        self.job = Job(
            repository="kinoko34077/sample", task_ref="kinoko34077/devflow#541",
            source_sha="a" * 40, recipe_id="audit.read",
            recipe_sha256="b" * 64, attempt_id="run-1",
            inputs={"mode": "audit", "dry": True},
        )
        self.policy = RecipePolicy(
            repository=self.job.repository, recipe_id=self.job.recipe_id,
            recipe_sha256=self.job.recipe_sha256,
            task_owners=frozenset({"kinoko34077/devflow"}),
            actors=frozenset({"central-chat"}), backends=frozenset(
                {"github_actions", "external_isolated"},
            ), input_schema={"mode": "str", "dry": "bool"},
        )
        digest = request_digest(self.job)
        self.claims = FakeClaims()
        self.claims.views[digest] = ClaimView(
            digest, self.job.repository, self.job.source_sha,
            self.job.attempt_id, 7, 200,
        )
        self.health = FakeHealth()
        self.backend = FakeBackend()
        self.gateway = OfflineGateway(
            policies=(self.policy,), hmac_key=self.auth_key,
            store=MemoryStore(), claims=self.claims,
            health=self.health, backend=self.backend,
        )
        self.issuer = TestPrincipalIssuer(self.issuer_key)
        self.ledger = SQLiteFakeJobLedger(self.path)
        self.addCleanup(self.ledger.close)
        self.runner = FakeIntegratedDispatch(
            issuer=self.issuer, gateway=self.gateway, ledger=self.ledger,
        )
        self.budget = FakeBudget(20, 3)

    def ingress(self, job=None):
        job = self.job if job is None else job
        fields = {"actor": "central-chat", "nonce": "nonce-1",
                  "issued_at": 100, "expires_at": 140}
        signature = hmac.new(self.auth_key, signing_payload(job, **fields),
                             hashlib.sha256).hexdigest()
        return SignedIngress("central-chat", "nonce-1", 100, 140, signature)

    def principal(self, job=None):
        return self.issuer.sign(
            actor="central-chat", repository=self.job.repository,
            job=self.job if job is None else job,
            issued_at=100, expires_at=140,
        )

    def execute(self, *, job=None, proof=None, principal=None, budget=None,
                now=110):
        return self.runner.execute_fake(
            self.job if job is None else job,
            self.ingress() if proof is None else proof,
            self.principal() if principal is None else principal,
            self.budget if budget is None else budget,
            now=now,
        )

    def denied(self, reason, operation):
        with self.assertRaises(FakeDispatchDenied) as err:
            operation()
        self.assertEqual(str(err.exception), reason)

    def test_native_fake_path_is_idempotent_after_durable_cas(self):
        first = self.execute()
        self.assertEqual((first.state, first.backend),
                         ("SIMULATED_RESULT", "github_actions"))
        self.assertEqual(self.execute(), first)
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(len(first.output_sha256), 64)

    def test_actions_outage_selects_independent_fake_adapter_only(self):
        self.health.view = replace(
            self.health.view, actions="CONTROL_OUTAGE",
        )
        row = self.execute()
        self.assertEqual((row.state, row.backend),
                         ("SIMULATED_RESULT", "external_isolated"))

    def test_fake_native_and_external_have_identical_output_contract(self):
        a = self.execute().output_sha256
        self.setUp()
        self.health.view = replace(
            self.health.view, actions="CAPACITY_BLOCKED",
        )
        b = self.execute().output_sha256
        self.assertEqual(a, b)

    def test_restart_with_new_gateway_cannot_run_same_digest(self):
        original = self.execute()
        new_ledger = SQLiteFakeJobLedger(self.path)
        self.addCleanup(new_ledger.close)
        fresh_backend = FakeBackend()
        fresh_gateway = OfflineGateway(
            policies=(self.policy,), hmac_key=self.auth_key,
            store=MemoryStore(), claims=self.claims, health=self.health,
            backend=fresh_backend,
        )
        other = FakeIntegratedDispatch(
            issuer=self.issuer, gateway=fresh_gateway, ledger=new_ledger,
        )
        replay = other.execute_fake(
            self.job, self.ingress(), self.principal(), self.budget, now=111,
        )
        self.assertEqual(original, replay)
        self.assertEqual(fresh_backend.calls, [])

    def test_fake_receipt_cannot_complete_another_job(self):
        class WrongReceiptBackend(FakeBackend):
            def run(self, job, digest, backend, epoch):
                receipt = super().run(job, digest, backend, epoch)
                return replace(receipt, request_digest="f" * 64)
        fake = WrongReceiptBackend()
        self.gateway.backend = fake
        row = self.execute()
        self.assertEqual(row.state, "UNCERTAIN")
        self.assertEqual(self.ledger.observe(request_digest(self.job)).state,
                         "UNCERTAIN")
        self.assertIsNone(self.ledger.observe("f" * 64))
        self.assertEqual(len(fake.calls), 1)

    def test_epoch_change_after_sqlite_cas_prevents_fake_backend_call(self):
        observed = self.gateway._claim
        count = [0]
        def change_at_second_observation(*args):
            value = observed(*args)
            count[0] += 1
            if count[0] == 2:
                digest = request_digest(self.job)
                self.claims.views[digest] = replace(
                    self.claims.views[digest], fence_epoch=8)
            return value
        self.gateway._claim = change_at_second_observation
        row = self.execute()
        self.assertEqual(row.state, "UNCERTAIN")
        self.assertEqual(self.backend.calls, [])

    def test_fake_crash_leaves_durable_uncertain_and_no_second_run(self):
        self.backend.fail_next = True
        row = self.execute()
        self.assertEqual(row.state, "UNCERTAIN")
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(self.execute(), row)
        self.assertEqual(len(self.backend.calls), 1)

    def test_claim_generation_or_source_stale_before_dispatch(self):
        digest = request_digest(self.job)
        original_claim = self.gateway._claim
        calls = [0]

        def change_after_admission(*args):
            observed = original_claim(*args)
            calls[0] += 1
            if calls[0] == 1:
                self.claims.views[digest] = replace(
                    self.claims.views[digest], fence_epoch=8,
                )
            return observed

        self.gateway._claim = change_after_admission
        self.denied("FAKE_PRE_DISPATCH_HOLD", self.execute)
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.ledger.observe(digest).state, "QUEUED")

    def test_old_claim_expired_denies_before_any_ledger_dispatch(self):
        digest = request_digest(self.job)
        self.claims.views[digest] = replace(
            self.claims.views[digest], lease_until=110,
        )
        self.denied("ADMISSION_OR_LEDGER_DENIED", self.execute)
        self.assertEqual(self.backend.calls, [])
        self.assertIsNone(self.ledger.observe(digest))

    def test_post_run_claim_changes_mark_uncertain_not_success(self):
        original = self.backend.run
        digest = request_digest(self.job)

        def fake_changed_claim(*args):
            response = original(*args)
            self.claims.views[digest] = replace(
                self.claims.views[digest], fence_epoch=8,
            )
            return response

        self.backend.run = fake_changed_claim
        row = self.execute()
        self.assertEqual(row.state, "UNCERTAIN")
        self.assertEqual(self.execute(), row)
        self.assertEqual(len(self.backend.calls), 1)

    def test_false_receipt_or_wrong_backend_does_not_complete(self):
        self.backend.run = lambda *args: Receipt(
            request_digest(self.job), "external_isolated", 7,
            "a" * 64, simulated=False,
        )
        row = self.execute()
        self.assertEqual(row.state, "UNCERTAIN")
        self.assertEqual(self.execute(), row)

    def test_tampered_test_principal_and_unauthorized_actor_rejected(self):
        token = self.principal()
        for tampered in (
            replace(token, signature="f" * 64),
            replace(token, actor="other"),
            replace(token, effect="MUTATE"),
            replace(token, repository="kinoko34077/other"),
            replace(token, job_digest="c" * 64),
        ):
            with self.subTest(field=tampered):
                self.denied("INVALID_TEST_PRINCIPAL",
                            lambda t=tampered: self.execute(principal=t))
        self.assertIsNone(self.ledger.observe(request_digest(self.job)))

    def test_expired_future_or_malformed_test_principal_rejected(self):
        token = self.principal()
        for x, now in (
            (token, 140),
            (replace(token, issued_at=120), 110),
            (replace(token, expires_at=1000), 110),
            (replace(token, issued_at=True), 110),
        ):
            with self.subTest(now=now, token=x):
                self.denied("INVALID_TEST_PRINCIPAL",
                            lambda t=x, n=now: self.execute(principal=t, now=n))

    def test_expired_real_ingress_cannot_be_satisfied_by_test_token(self):
        self.denied("ADMISSION_OR_LEDGER_DENIED", lambda: self.execute(
            proof=replace(self.ingress(), signature="0" * 64),
        ))
        self.assertEqual(self.backend.calls, [])

    def test_tampered_target_digest_is_rejected_before_queue(self):
        changed = replace(self.job, source_sha="c" * 40)
        self.denied("INVALID_TEST_PRINCIPAL",
                    lambda: self.execute(job=changed))
        self.assertEqual(self.backend.calls, [])

    def test_fallback_never_overrides_policy_disabled_or_api_outage(self):
        for actions, api in (
            ("POLICY_DISABLED", "VERIFIED"),
            ("CONTROL_OUTAGE", "UNKNOWN"),
        ):
            with self.subTest(actions=actions):
                self.setUp()
                self.health.view = replace(
                    self.health.view, actions=actions, github_api=api,
                )
                self.denied("ADMISSION_OR_LEDGER_DENIED", self.execute)
                self.assertEqual(self.backend.calls, [])

    def test_unbounded_budget_and_effectful_adapter_denied(self):
        for budget in (FakeBudget(0, 3), FakeBudget(61, 3),
                       FakeBudget(30, 0), FakeBudget(30, 101),
                       FakeBudget(True, 3)):
            self.denied("FAKE_BUDGET_DENIED",
                        lambda b=budget: self.execute(budget=b))
        self.assertEqual(self.backend.calls, [])

    def test_no_secrets_or_private_inputs_in_sqlite_receipt(self):
        row = self.execute()
        self.assertNotIn("F2C-", repr(row))
        self.assertNotIn("central-chat", row.output_sha256)
        self.assertNotIn("audit", row.output_sha256)
        self.assertEqual(set(row.__dataclass_fields__),
                         {"digest", "repository", "task_ref", "source_sha",
                          "recipe_sha256", "attempt_id", "actor", "nonce",
                          "epoch", "state", "backend", "output_sha256"})

    def test_wrong_test_issuer_cannot_verify_principal(self):
        wrong_issuer = TestPrincipalIssuer(b"unrelated-injected-test-key-with-32-bytes")
        other = FakeIntegratedDispatch(
            issuer=wrong_issuer, gateway=self.gateway, ledger=self.ledger,
        )
        self.denied("INVALID_TEST_PRINCIPAL",
                    lambda: other.execute_fake(
                        self.job, self.ingress(), self.principal(),
                        self.budget, now=110,
                    ))
        self.assertEqual(self.backend.calls, [])


if __name__ == "__main__":
    unittest.main()
