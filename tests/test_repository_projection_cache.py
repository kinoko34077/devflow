import copy
import unittest

from tools import maintenance_sync_check
from tools import repository_projection_cache as cache


REPOSITORY = "kinoko34077/demo"
GENERATED_AT = "2026-10-04T05:50:00Z"
OBSERVED_AT = "2026-10-04T05:49:00Z"


def live_projection(
    *,
    source_status="AVAILABLE",
    source_freshness="CURRENT",
    machine_task_count=0,
    coverage_complete=False,
):
    records = []
    if source_status == "AVAILABLE" and coverage_complete:
        records = [
            {
                "issue_number": number,
                "title": f"record {number}",
                "state": "open",
                "created_at": f"2026-10-04T0{number}:00:00Z",
                "updated_at": f"2026-10-04T0{number}:30:00Z",
                "url": f"https://github.com/kinoko34077/demo/issues/{number}",
                "source_kind": "MACHINE",
                "record_role": "REFERENCE",
                "type": "DOCS",
                "work_status": "AUDITED",
                "attention_disposition": None,
                "metadata_error": None,
            }
            for number in (1, 2, 3)
        ]
    return {
        "repository": REPOSITORY,
        "observed_at": OBSERVED_AT,
        "source_status": source_status,
        "source_freshness": source_freshness,
        "source_error": None if source_status == "AVAILABLE" else "read failed",
        "open_issue_count": 3 if source_status == "AVAILABLE" else 0,
        "machine_task_count": machine_task_count,
        "legacy_hint_count": (
            0 if coverage_complete or source_status != "AVAILABLE" else 1
        ),
        "unclassified_count": (
            0 if coverage_complete or source_status != "AVAILABLE" else 2
        ),
        "invalid_metadata_count": 0,
        "untrusted_metadata_count": 0,
        "machine_type_counts": {},
        "legacy_hint_type_counts": (
            {}
            if coverage_complete or source_status != "AVAILABLE"
            else {"BUG": 1}
        ),
        "task_records": [],
        "ready_tasks": [],
        "implementing_tasks": [],
        "newest_open_issue": {
            "issue_number": 3,
            "title": "[BUG] newest",
            "state": "open",
            "created_at": "2026-10-04T03:00:00Z",
            "updated_at": "2026-10-04T03:30:00Z",
            "url": "https://github.com/kinoko34077/demo/issues/3",
            "source_kind": "LEGACY_HINT",
            "record_role": None,
            "type": "BUG",
            "work_status": None,
            "attention_disposition": None,
            "metadata_error": None,
        } if source_status == "AVAILABLE" else None,
        "recently_active_issue": {
            "issue_number": 1,
            "title": "recent",
            "state": "open",
            "created_at": "2026-10-04T01:00:00Z",
            "updated_at": "2026-10-04T04:00:00Z",
            "url": "https://github.com/kinoko34077/demo/issues/1",
            "source_kind": "UNCLASSIFIED",
            "record_role": None,
            "type": None,
            "work_status": None,
            "attention_disposition": None,
            "metadata_error": None,
        } if source_status == "AVAILABLE" else None,
        "records": records,
    }


def verified_control_trust(*, freshness="CURRENT"):
    return {
        "status": "VERIFIED",
        "freshness": freshness,
        "source": "DEVFLOW_SHARED_CONTROL_VERIFIER",
        "observed_at": OBSERVED_AT,
        "detail": None,
    }


class RepositoryProjectionCacheSchemaTests(unittest.TestCase):
    def test_build_current_incomplete_cache_keeps_zero_task_ambiguous(self):
        payload = cache.build_cached_projection(
            REPOSITORY,
            live_projection(machine_task_count=0, coverage_complete=False),
            generated_at=GENERATED_AT,
            control_trust=verified_control_trust(),
        )

        self.assertEqual(payload["schema_version"], cache.CACHE_SCHEMA_VERSION)
        self.assertEqual(payload["repository"], REPOSITORY)
        self.assertEqual(payload["generated_at"], GENERATED_AT)
        self.assertEqual(payload["valid_until"], "2026-10-05T05:50:00Z")
        self.assertEqual(payload["source"]["status"], "AVAILABLE")
        self.assertEqual(payload["source"]["freshness"], "CURRENT")
        self.assertRegex(payload["source"]["digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(payload["generation_id"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(payload["counts"]["machine_tasks"], 0)
        self.assertEqual(payload["coverage"]["status"], "INCOMPLETE")
        self.assertTrue(payload["coverage"]["ambiguous"])
        self.assertEqual(
            payload["coverage"]["active_work_evidence"],
            "NO_MACHINE_TASK_EVIDENCE",
        )
        self.assertFalse(payload["coverage"]["can_replace_manual_active_work"])

    def test_complete_coverage_can_distinguish_zero_machine_tasks(self):
        payload = cache.build_cached_projection(
            REPOSITORY,
            live_projection(
                machine_task_count=0,
                coverage_complete=True,
            ),
            generated_at=GENERATED_AT,
            control_trust=verified_control_trust(),
        )
        self.assertEqual(payload["coverage"]["status"], "COMPLETE")
        self.assertFalse(payload["coverage"]["ambiguous"])
        self.assertEqual(
            payload["coverage"]["active_work_evidence"],
            "NO_MACHINE_TASKS_UNDER_COMPLETE_COVERAGE",
        )
        self.assertFalse(payload["coverage"]["can_replace_manual_active_work"])

    def test_source_unavailable_is_explicit_and_cannot_assert_no_active_work(self):
        payload = cache.build_cached_projection(
            REPOSITORY,
            live_projection(
                source_status="UNAVAILABLE",
                source_freshness="UNKNOWN",
            ),
            generated_at=GENERATED_AT,
            control_trust=verified_control_trust(freshness="UNKNOWN"),
        )
        self.assertEqual(payload["source"]["status"], "UNAVAILABLE")
        self.assertEqual(payload["source"]["freshness"], "UNKNOWN")
        self.assertEqual(payload["coverage"]["status"], "UNAVAILABLE")
        self.assertTrue(payload["coverage"]["ambiguous"])
        self.assertEqual(
            payload["coverage"]["active_work_evidence"],
            "SOURCE_UNAVAILABLE",
        )
        self.assertFalse(payload["coverage"]["can_replace_manual_active_work"])

    def test_stale_source_is_explicit_and_fail_closed(self):
        payload = cache.build_cached_projection(
            REPOSITORY,
            live_projection(source_freshness="STALE"),
            generated_at=GENERATED_AT,
            control_trust=verified_control_trust(freshness="STALE"),
        )
        self.assertEqual(payload["source"]["freshness"], "STALE")
        self.assertEqual(payload["coverage"]["status"], "STALE")
        self.assertTrue(payload["coverage"]["ambiguous"])
        self.assertFalse(payload["coverage"]["can_replace_manual_active_work"])
        self.assertEqual(payload["control_trust"]["freshness"], "STALE")

    def test_control_trust_transport_is_explicit(self):
        payload = cache.build_cached_projection(
            REPOSITORY,
            live_projection(),
            generated_at=GENERATED_AT,
            control_trust=verified_control_trust(),
        )
        self.assertEqual(
            payload["control_trust"],
            {
                "status": "VERIFIED",
                "freshness": "CURRENT",
                "source": "DEVFLOW_SHARED_CONTROL_VERIFIER",
                "observed_at": OBSERVED_AT,
                "detail": None,
            },
        )

    def test_cache_validity_window_is_producer_owned_and_fail_closed_after_expiry(self):
        payload = cache.build_cached_projection(
            REPOSITORY,
            live_projection(),
            generated_at=GENERATED_AT,
            control_trust=verified_control_trust(),
        )
        self.assertEqual(
            cache.effective_cache_freshness(
                payload,
                now="2026-10-05T05:49:59Z",
            ),
            "CURRENT",
        )
        self.assertEqual(
            cache.effective_cache_freshness(
                payload,
                now="2026-10-05T05:50:01Z",
            ),
            "STALE",
        )

    def test_source_unavailable_is_never_effectively_current(self):
        payload = cache.build_cached_projection(
            REPOSITORY,
            live_projection(
                source_status="UNAVAILABLE",
                source_freshness="UNKNOWN",
            ),
            generated_at=GENERATED_AT,
            control_trust=verified_control_trust(),
        )
        self.assertEqual(
            cache.effective_cache_freshness(
                payload,
                now="2026-10-04T06:00:00Z",
            ),
            "UNAVAILABLE",
        )

    def test_source_digest_is_stable_across_observation_time_but_generation_changes(self):
        first_live = live_projection()
        second_live = copy.deepcopy(first_live)
        second_live["observed_at"] = "2026-10-04T05:59:00Z"
        second_live["source_freshness"] = "STALE"

        first = cache.build_cached_projection(
            REPOSITORY,
            first_live,
            generated_at=GENERATED_AT,
            control_trust=verified_control_trust(),
        )
        second = cache.build_cached_projection(
            REPOSITORY,
            second_live,
            generated_at="2026-10-04T06:00:00Z",
            control_trust={
                **verified_control_trust(freshness="STALE"),
                "observed_at": "2026-10-04T05:59:00Z",
            },
        )
        self.assertEqual(first["source"]["digest"], second["source"]["digest"])
        self.assertNotEqual(first["generation_id"], second["generation_id"])


class RepositoryProjectionCacheMarkerTests(unittest.TestCase):
    def _payload(self):
        return cache.build_cached_projection(
            REPOSITORY,
            live_projection(),
            generated_at=GENERATED_AT,
            control_trust=verified_control_trust(),
        )

    def test_round_trip_marker_cache(self):
        body = "## Repository\n\n`kinoko34077/demo`\n"
        updated = cache.replace_cached_projection(
            body,
            REPOSITORY,
            self._payload(),
            expected_body_sha256=maintenance_sync_check.canonical_body_sha256(body),
        )
        parsed = cache.parse_cached_projection(updated, REPOSITORY)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.payload, self._payload())

    def test_duplicate_marker_pair_fails_closed(self):
        body = "human text"
        updated = cache.replace_cached_projection(
            body,
            REPOSITORY,
            self._payload(),
            expected_body_sha256=maintenance_sync_check.canonical_body_sha256(body),
        )
        duplicate = updated + "\n\n" + updated[updated.index(cache.CACHE_MARKER_BEGIN):]
        with self.assertRaisesRegex(
            cache.RepositoryProjectionCacheError,
            "exactly one marker pair",
        ):
            cache.parse_cached_projection(duplicate, REPOSITORY)

    def test_malformed_unknown_and_unsupported_schema_fail_closed(self):
        malformed = (
            f"{cache.CACHE_MARKER_BEGIN}\n{{not json}}\n"
            f"{cache.CACHE_MARKER_END}"
        )
        with self.assertRaisesRegex(cache.RepositoryProjectionCacheError, "malformed"):
            cache.parse_cached_projection(malformed, REPOSITORY)

        payload = self._payload()
        unknown = copy.deepcopy(payload)
        unknown["surprise"] = True
        body = cache.render_cached_projection(unknown)
        with self.assertRaisesRegex(cache.RepositoryProjectionCacheError, "unknown"):
            cache.parse_cached_projection(body, REPOSITORY)

        unsupported = copy.deepcopy(payload)
        unsupported["schema_version"] = "repository-projection-cache.v2"
        body = cache.render_cached_projection(unsupported)
        with self.assertRaisesRegex(
            cache.RepositoryProjectionCacheError,
            "schema_version",
        ):
            cache.parse_cached_projection(body, REPOSITORY)

    def test_repository_identity_mismatch_fails_closed(self):
        body = cache.render_cached_projection(self._payload())
        with self.assertRaisesRegex(
            cache.RepositoryProjectionCacheError,
            "repository identity mismatch",
        ):
            cache.parse_cached_projection(body, "kinoko34077/other")

    def test_exact_prewrite_body_digest_fences_stale_write(self):
        body = "## Repository\n\n`kinoko34077/demo`\n"
        stale_digest = maintenance_sync_check.canonical_body_sha256(body)
        changed = body + "\nHuman edit after read.\n"
        with self.assertRaisesRegex(
            cache.RepositoryProjectionCacheError,
            "body digest",
        ):
            cache.replace_cached_projection(
                changed,
                REPOSITORY,
                self._payload(),
                expected_body_sha256=stale_digest,
            )

    def test_human_text_outside_marker_block_is_preserved(self):
        body = (
            "## Repository\n\n`kinoko34077/demo`\n\n"
            "## Active Work\n\nHuman-owned prose.\n"
        )
        first = cache.replace_cached_projection(
            body,
            REPOSITORY,
            self._payload(),
            expected_body_sha256=maintenance_sync_check.canonical_body_sha256(body),
        )
        changed_payload = copy.deepcopy(self._payload())
        changed_payload["generated_at"] = "2026-10-04T05:51:00Z"
        changed_payload["valid_until"] = "2026-10-05T05:51:00Z"
        changed_payload = cache.recompute_generation_id(changed_payload)
        second = cache.replace_cached_projection(
            first,
            REPOSITORY,
            changed_payload,
            expected_body_sha256=maintenance_sync_check.canonical_body_sha256(first),
        )
        self.assertTrue(first.startswith(body.rstrip()))
        self.assertTrue(second.startswith(body.rstrip()))
        before_first = first.split(cache.CACHE_MARKER_BEGIN, 1)[0]
        before_second = second.split(cache.CACHE_MARKER_BEGIN, 1)[0]
        self.assertEqual(before_first, before_second)
        self.assertIn("Human-owned prose.", second)


if __name__ == "__main__":
    unittest.main()
