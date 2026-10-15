from __future__ import annotations

import hashlib
import hmac
import unittest
from dataclasses import replace

from tools.central_execution_gateway import (
    ClaimView, Denied, FakeBackend, FakeClaims, FakeHealth,
    Job, MemoryStore, OfflineGateway, RecipePolicy, SignedIngress,
    request_digest, signing_payload,
)


class OfflineCentralGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.key = b"F2A-test-only-central-HMAC-key-32+bytes"
        self.policy = RecipePolicy(
            repository="kinoko34077/sample",
            recipe_id="audit.read",
            recipe_sha256="a" * 64,
            task_owners=frozenset({"kinoko34077/devflow"}),
            actors=frozenset({"central-chat"}),
            input_schema={"mode": "str", "limit": "int", "dry_run": "bool"},
            backends=frozenset({"github_actions", "external_isolated"}),
        )
        self.job = Job(
            repository="kinoko34077/sample",
            task_ref="kinoko34077/devflow#541",
            source_sha="b" * 40,
            recipe_id="audit.read",
            recipe_sha256=self.policy.recipe_sha256,
            attempt_id="attempt-1",
            inputs={"mode": "audit", "limit": 3, "dry_run": True},
        )
        self.claims = FakeClaims()
        self.health = FakeHealth()
        self.backend = FakeBackend()
        self.store = MemoryStore()
        self.digest = request_digest(self.job)
        self.claims.views[self.digest] = ClaimView(
            self.digest, self.job.repository, self.job.source_sha,
            self.job.attempt_id, 7, 200,
        )
        self.gateway = OfflineGateway(
            policies=(self.policy,), hmac_key=self.key, store=self.store,
            claims=self.claims, health=self.health, backend=self.backend,
        )

    def proof(self, job=None, *, nonce="nonce-1", actor="central-chat",
              issued=100, expiry=140) -> SignedIngress:
        job = self.job if job is None else job
        body = signing_payload(
            job, actor=actor, nonce=nonce,
            issued_at=issued, expires_at=expiry,
        )
        return SignedIngress(
            actor, nonce, issued, expiry,
            hmac.new(self.key, body, hashlib.sha256).hexdigest(),
        )

    def submit(self, *, now=110, job=None, proof=None):
        job = self.job if job is None else job
        proof = self.proof(job) if proof is None else proof
        return self.gateway.submit(job, proof, now=now)

    def denies(self, reason, f) -> None:
        with self.assertRaises(Denied) as cm:
            f()
        self.assertEqual(str(cm.exception), reason)

    def test_native_preferred_and_simulated_receipt(self) -> None:
        queued = self.submit()
        self.assertEqual((queued.state, queued.backend), ("QUEUED", None))
        result = self.gateway.run_next(now=111)
        self.assertEqual((result.state, result.backend), ("SIMULATED_RESULT", "github_actions"))
        self.assertTrue(result.receipt.simulated)
        self.assertEqual(result.receipt.request_digest, self.digest)
        self.assertEqual(len(result.receipt.output_sha256), 64)
        self.assertEqual(self.gateway.run_next(now=112), None)
        self.assertEqual(len(self.backend.calls), 1)

    def test_external_when_actions_control_or_capacity_unavailable(self):
        observed = []
        for reason in ("CONTROL_OUTAGE", "CAPACITY_BLOCKED"):
            with self.subTest(reason=reason):
                self.setUp()
                self.health.view = replace(self.health.view, actions=reason)
                self.submit()
                result = self.gateway.run_next(now=111)
                self.assertEqual((result.state, result.backend),
                                 ("SIMULATED_RESULT", "external_isolated"))
                observed.append(result.receipt.output_sha256)
        self.assertEqual(observed[0], observed[1])

    def test_native_external_fake_outputs_equivalent(self):
        self.submit()
        native = self.gateway.run_next(now=111)
        self.setUp()
        self.health.view = replace(self.health.view, actions="CONTROL_OUTAGE")
        self.submit()
        external = self.gateway.run_next(now=111)
        self.assertEqual(native.receipt.output_sha256, external.receipt.output_sha256)

    def test_policy_disabled_unknown_and_api_down_never_dispatch(self):
        for actions, github_api in (
            ("POLICY_DISABLED", "VERIFIED"),
            ("UNKNOWN", "VERIFIED"),
            ("READY", "UNAVAILABLE"),
            ("CONTROL_OUTAGE", "UNKNOWN"),
        ):
            with self.subTest(actions=actions, api=github_api):
                self.setUp()
                self.health.view = replace(
                    self.health.view, actions=actions, github_api=github_api,
                )
                self.denies("BACKEND_UNAVAILABLE", self.submit)
                self.assertEqual(self.backend.calls, [])

    def test_external_unavailable_or_unlisted_fails_closed(self):
        self.health.view = replace(
            self.health.view, actions="CONTROL_OUTAGE", external="UNAVAILABLE",
        )
        self.denies("BACKEND_UNAVAILABLE", self.submit)
        self.policy = replace(
            self.policy, backends=frozenset({"github_actions"}),
        )
        self.gateway = OfflineGateway(
            policies=(self.policy,), hmac_key=self.key, store=self.store,
            claims=self.claims, health=self.health, backend=self.backend,
        )
        self.denies("BACKEND_UNAVAILABLE", self.submit)

    def test_auth_expired_future_bad_hmac_and_wrong_actor(self):
        for proof, reason in (
            (replace(self.proof(), signature="0" * 64), "INVALID_SIGNATURE"),
            (self.proof(), "INVALID_INGRESS"),
            (self.proof(issued=120, expiry=140), "INVALID_INGRESS"),
            (self.proof(issued=1, expiry=600), "INVALID_INGRESS"),
            (self.proof(actor="outsider"), "INVALID_INGRESS"),
        ):
            with self.subTest(reason=reason, proof=proof):
                self.denies(reason, lambda p=proof: self.submit(
                    proof=p, now=141 if p.issued_at == 100 and
                    reason == "INVALID_INGRESS" and p.actor == "central-chat"
                    else 110,
                ))

    def test_payload_bound_hmac(self):
        evil = replace(self.job, inputs={**self.job.inputs, "limit": 4})
        self.denies("INVALID_SIGNATURE",
                    lambda: self.submit(job=evil, proof=self.proof()))
        self.assertEqual(self.backend.calls, [])

    def test_authorized_cross_repo_ownership_not_any_owner(self):
        self.submit()
        job = replace(self.job, task_ref="attacker/rogue#42")
        self.denies("CATALOG_DENIED",
                    lambda: self.submit(job=job, proof=self.proof(job, nonce="nonce-2")))
        job = replace(self.job, task_ref="kinoko34077/sample#7")
        dig = request_digest(job)
        self.claims.views[dig] = ClaimView(dig, job.repository, job.source_sha,
                                            job.attempt_id, 7, 200)
        rec = self.submit(job=job, proof=self.proof(job, nonce="nonce-3"))
        self.assertEqual(rec.state, "QUEUED")

    def test_catalog_cannot_be_client_target_substituted(self):
        for repo in ("kinoko34077/private", "evil/rogue",
                     "Kinoko34077/sample", "kinoko34077/-sample"):
            with self.subTest(repo=repo):
                job = replace(self.job, repository=repo)
                self.denies("CATALOG_DENIED",
                            lambda: self.submit(job=job, proof=self.proof(job, nonce="different")))

    def test_unauthorized_recipe_digest_and_shell_extra_rejected(self):
        for job in (
            replace(self.job, recipe_sha256="f" * 64),
            replace(self.job, source_sha="main"),
            replace(self.job, inputs={**self.job.inputs, "cmd": "whoami"}),
            replace(self.job, inputs={**self.job.inputs, "limit": True}),
            replace(self.job, inputs={**self.job.inputs, "mode": "audit\ninject"}),
            replace(self.job, inputs={**self.job.inputs, "mode": "\u202eevil"}),
            replace(self.job, inputs={**self.job.inputs, "mode": "\ud800"}),
            replace(self.job, inputs={**self.job.inputs, "mode": "x" * 1025}),
        ):
            with self.subTest(job=repr(job)[:80]):
                self.denies("CATALOG_DENIED",
                            lambda j=job: self.submit(job=j, proof=self.proof(j)))

    def test_missing_claim_and_stale_claim_source_epoch(self):
        self.claims.views.clear()
        self.denies("AUTHORITY_UNAVAILABLE", self.submit)
        self.claims.views[self.digest] = ClaimView(
            self.digest, self.job.repository, "c" * 40, self.job.attempt_id, 7, 200,
        )
        self.denies("CLAIM_STALE_OR_MISMATCHED", self.submit)
        self.claims.views[self.digest] = ClaimView(
            self.digest, self.job.repository, self.job.source_sha,
            self.job.attempt_id, 7, 100,
        )
        self.denies("CLAIM_STALE_OR_MISMATCHED", self.submit)

    def test_fencing_epoch_changed_before_dispatch_holds(self):
        self.submit()
        self.claims.views[self.digest] = replace(
            self.claims.views[self.digest], fence_epoch=8,
        )
        r = self.gateway.run_next(now=111)
        self.assertEqual((r.state, r.reason), ("HELD", "STALE_FENCE_EPOCH"))
        self.assertEqual(self.backend.calls, [])

    def test_claim_expired_before_dispatch_holds(self):
        self.submit()
        self.claims.views[self.digest] = replace(
            self.claims.views[self.digest], lease_until=111,
        )
        r = self.gateway.run_next(now=111)
        self.assertEqual((r.state, r.reason), ("HELD", "CLAIM_STALE_OR_MISMATCHED"))
        self.assertEqual(self.backend.calls, [])

    def test_health_changed_before_dispatch_holds(self):
        self.submit()
        self.health.view = replace(self.health.view, actions="POLICY_DISABLED")
        r = self.gateway.run_next(now=111)
        self.assertEqual((r.state, r.reason), ("HELD", "BACKEND_UNAVAILABLE"))
        self.assertEqual(self.backend.calls, [])

    def test_unknown_outcome_stays_uncertain_no_duplicate_run(self):
        self.submit()
        self.backend.fail_next = True
        first = self.gateway.run_next(now=111)
        self.assertEqual((first.state, first.reason), ("UNCERTAIN", "UNKNOWN_OUTCOME"))
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(self.gateway.run_next(now=112), None)
        self.assertEqual(self.submit(), first)
        self.assertEqual(len(self.backend.calls), 1)

    def test_idempotence_persists_only_across_simulated_store_reuse(self):
        self.submit()
        completed = self.gateway.run_next(now=111)
        other = OfflineGateway(
            policies=(self.policy,), hmac_key=self.key, store=self.store,
            claims=self.claims, health=self.health, backend=self.backend,
        )
        self.assertEqual(other.submit(self.job, self.proof(), now=112), completed)
        self.assertEqual(other.run_next(now=113), None)
        self.assertEqual(len(self.backend.calls), 1)

    def test_reused_nonce_for_different_job_rejected(self):
        self.submit()
        other = replace(self.job, attempt_id="attempt-2")
        digest = request_digest(other)
        self.claims.views[digest] = ClaimView(
            digest, other.repository, other.source_sha, other.attempt_id, 7, 200,
        )
        self.denies("NONCE_REPLAY",
                    lambda: self.submit(job=other, proof=self.proof(other)))

    def test_unapproved_fake_not_replaceable_by_effectful_host(self):
        class PretendBackend:
            def run(self, *args):  # pragma: no cover - must never be called
                raise AssertionError("not isolated fake")
        self.denies(
            "NOT_OFFLINE_FAKE_ADAPTER",
            lambda: OfflineGateway(
                policies=(self.policy,), hmac_key=self.key, store=self.store,
                claims=self.claims, health=self.health, backend=PretendBackend(),
            ),
        )

    def test_duplicate_catalog_and_invalid_hmac_key_rejected(self):
        self.denies("DUPLICATE_CATALOG_ENTRY", lambda: OfflineGateway(
            policies=(self.policy, self.policy), hmac_key=self.key,
            store=self.store, claims=self.claims, health=self.health, backend=self.backend,
        ))
        self.denies("INVALID_VERIFIER_KEY", lambda: OfflineGateway(
            policies=(self.policy,), hmac_key=b"short", store=self.store,
            claims=self.claims, health=self.health, backend=self.backend,
        ))

    def test_no_live_effect_or_credential_in_receipt(self):
        self.submit()
        receipt = self.gateway.run_next(now=111).receipt
        self.assertEqual(set(vars(receipt)),
                         {"request_digest", "backend", "fence_epoch",
                          "output_sha256", "simulated"})
        self.assertNotIn("kinoko", repr(receipt))
        self.assertNotIn("F2A-test-only", repr(receipt))


if __name__ == "__main__":
    unittest.main()
