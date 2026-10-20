"""Strict and non-authoritative v2 SMC run-scope attestation tests."""
import json
import unittest

from tools.maintenance_catalog import ResolvedSlot, Scope
from tools.maintenance_ledger import ActiveRun, RunRecord, parse_run_comment
from tools.maintenance_run_attestation import (
    ATTESTATION_SENTINEL, RunAttestationError,
    bind_attested_run, parse_attested_run_comment, render_attested_run_comment,
)

REPO = "kinoko34077/example"
FP = "sha256:" + "a" * 64
DIGEST = "sha256:" + "b" * 64
RUN_ID = f"audit:{REPO}:common.correctness:1"


def active(**changes):
    d = dict(
        repository=REPO, run_id=RUN_ID, slot_id="common.correctness",
        generation=1, catalog_digest=DIGEST, fingerprint=FP,
        depth="STANDARD", coverage_key="common.correctness",
        selected_at="2026-10-16T00:00:00Z", publisher_attempt_id="a",
        score_breakdown=(("never_run", 40),),
    )
    d.update(changes)
    return ActiveRun(**d)


def slot(**changes):
    d = dict(
        repository=REPO, slot_id="common.correctness", title="Correctness",
        lifecycle="ACTIVE", scope=Scope("repository", "."),
        lens="correctness", coverage_key="common.correctness",
        risk="HIGH", cadence_class="GENERAL", minimum_depth="STANDARD",
        external_freshness_class="NORMAL", description="Read only", source="common",
    )
    d.update(changes)
    return ResolvedSlot(**d)


def record(**changes):
    d = dict(
        repository=REPO, run_id=RUN_ID, slot_id="common.correctness",
        generation=1, lens="correctness", depth="STANDARD",
        fingerprint=FP, result="CLEAN", findings_summary="verified bounded",
        completed_at="2026-10-16T00:15:00Z", next_eligibility_reason=None,
        evidence_refs=(f"https://github.com/{REPO}/issues/1",),
    )
    d.update(changes)
    return RunRecord(**d)


def value():
    return bind_attested_run(active(), slot(), record(), DIGEST)


class ImmutableAttestationTests(unittest.TestCase):
    def test_canonical_v2_round_trip_and_v1_separation(self):
        obj = value()
        text = render_attested_run_comment(obj)
        self.assertEqual(obj, parse_attested_run_comment(text))
        self.assertIsNone(parse_run_comment(text))
        self.assertEqual(text, render_attested_run_comment(parse_attested_run_comment(text)))

    def test_old_v1_or_nonmachine_comment_does_not_upgrade(self):
        self.assertIsNone(parse_attested_run_comment("human note"))
        self.assertIsNone(parse_attested_run_comment("<!-- devflow-maintenance-run:v1 -->"))

    def test_binding_preserves_exact_scope_and_digest(self):
        attestation = value()
        self.assertEqual("repository", attestation.scope.kind)
        self.assertEqual(".", attestation.scope.selector)
        self.assertEqual("common.correctness", attestation.coverage_key)
        self.assertEqual(DIGEST, attestation.catalog_digest)

    def test_selection_digest_rotation_must_not_be_backfilled(self):
        for changed in (
            DIGEST[:-1] + "c",
            "sha256:wrong",
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(RunAttestationError):
                    bind_attested_run(active(), slot(), record(), changed)

    def test_source_fingerprint_and_generation_mismatch_fail(self):
        scenarios = (
            (active(fingerprint="sha256:" + "c"*64), slot(), record()),
            (active(generation=2), slot(), record()),
            (active(), slot(), record(fingerprint="sha256:" + "c"*64)),
            (active(), slot(), record(run_id=RUN_ID.replace(":1", ":2"), generation=2)),
            (active(), slot(lens="security"), record()),
            (active(), slot(scope=Scope("component", "other"), coverage_key="other"), record()),
        )
        for a, s, r in scenarios:
            with self.subTest(a=a, s=s):
                with self.assertRaises(RunAttestationError):
                    bind_attested_run(a, s, r, DIGEST)

    def test_scope_is_exact_and_not_inferred_after_catalog_change(self):
        from tools.maintenance_run_attestation import AttestedRun
        obj = value()
        changed = AttestedRun(record=obj.record, scope=Scope("component", "new"),
                              coverage_key=obj.coverage_key, catalog_digest=obj.catalog_digest)
        self.assertNotEqual(render_attested_run_comment(obj), render_attested_run_comment(changed))

    def test_bad_scope_kind_or_blank_name_is_rejected(self):
        from tools.maintenance_run_attestation import AttestedRun
        obj = value()
        for scope in (Scope("other", "."), Scope("repository", "  ")):
            with self.subTest(scope=scope):
                with self.assertRaises(RunAttestationError):
                    render_attested_run_comment(AttestedRun(obj.record, scope, obj.coverage_key, DIGEST))

    def test_v2_scope_and_coverage_nonstring_values_fail_with_contract_error(self):
        from tools.maintenance_run_attestation import AttestedRun

        obj = value()
        canonical = render_attested_run_comment(obj)
        fields = (
            ('"kind":"repository"', "kind", "scope kind"),
            ('"selector":"."', "selector", "scope selector"),
            ('"coverage_key":"common.correctness"', "coverage_key", "coverage key"),
        )
        malformed = ([], {}, 123, True, False, None)
        for source, field, name in fields:
            self.assertIn(source, canonical)
            for bad in malformed:
                with self.subTest(field=name, bad=bad):
                    raw = canonical.replace(
                        source, '"' + field + '":' + json.dumps(bad), 1,
                    )
                    with self.assertRaises(RunAttestationError):
                        parse_attested_run_comment(raw)

                    scope = Scope(bad, ".") if field == "kind" else (
                        Scope("repository", bad) if field == "selector" else obj.scope
                    )
                    key = bad if field == "coverage_key" else obj.coverage_key
                    with self.assertRaises(RunAttestationError):
                        render_attested_run_comment(
                            AttestedRun(obj.record, scope, key, DIGEST),
                        )

    def test_duplicate_json_keys_rejected_even_nested(self):
        text = render_attested_run_comment(value())
        mutated = text.replace('"coverage_key":"common.correctness"',
                               '"coverage_key":"common.correctness","coverage_key":"other"', 1)
        with self.assertRaisesRegex(RunAttestationError, "duplicate"):
            parse_attested_run_comment(mutated)

    def test_unknown_schema_and_extra_fields_fail(self):
        text = render_attested_run_comment(value())
        for changed in (
            text.replace("maintenance-run.v2", "maintenance-run.v999", 1),
            text.replace('"schema_version":"maintenance-run.v2"',
                         '"new":true,"schema_version":"maintenance-run.v2"'),
        ):
            with self.subTest(changed=changed[:70]):
                with self.assertRaises(RunAttestationError):
                    parse_attested_run_comment(changed)

    def test_repeated_sentinel_and_dirty_wrapping_fail(self):
        text = render_attested_run_comment(value())
        for malformed in (text + "\n" + ATTESTATION_SENTINEL, "prefix\n" + text):
            with self.subTest(length=len(malformed)):
                with self.assertRaises(RunAttestationError):
                    parse_attested_run_comment(malformed)

    def test_invalid_run_timestamp_result_and_runid_fail(self):
        for changed in (
            record(completed_at="yesterday"),
            record(result="OK"),
            record(run_id="unrelated"),
            record(evidence_refs=("bad",), generation=0),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(RunAttestationError):
                    bind_attested_run(active(), slot(), changed, DIGEST)

    def test_invalid_underlying_record_fields_inside_json_fail(self):
        text = render_attested_run_comment(value())
        for wrong in (
            text.replace('"result":"CLEAN"', '"result":"PASSED"'),
            text.replace('"generation":1', '"generation":"1"'),
            text.replace('"fingerprint":"' + FP + '"', '"fingerprint":"sha256:nothex"'),
        ):
            with self.subTest(wrong=wrong[:60]):
                with self.assertRaises(RunAttestationError):
                    parse_attested_run_comment(wrong)

    def test_unknown_run_fields_are_rejected(self):
        text = render_attested_run_comment(value())
        malformed = text.replace('"evidence_refs":[', '"untrusted":true,"evidence_refs":[')
        with self.assertRaises(RunAttestationError):
            parse_attested_run_comment(malformed)


if __name__ == "__main__":
    unittest.main()
