import copy
import json
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

    def test_all_state_preview_preserves_review_blocked_and_zero_authority(self):
        live = live_projection(machine_task_count=2, coverage_complete=True)
        live["task_records"] = [
            {
                "issue_number": number, "title": f"Task {number}",
                "url": f"https://github.com/kinoko34077/demo/issues/{number}",
                "source_kind": "MACHINE", "record_role": "TASK",
                "type": "FEATURE", "work_status": status,
                "attention_disposition": None,
            }
            for number, status in ((1, "AWAITING_REVIEW"), (2, "BLOCKED"))
        ]
        payload = cache.build_cached_projection(
            REPOSITORY, live, generated_at=GENERATED_AT,
            control_trust=verified_control_trust(),
        )
        self.assertEqual(payload["all_state_tasks"]["status"], "COMPLETE")
        self.assertEqual(payload["all_state_tasks"]["total"], 2)
        self.assertEqual(
            [item["work_status"] for item in payload["all_state_tasks"]["records"]],
            ["AWAITING_REVIEW", "BLOCKED"],
        )
        self.assertEqual(payload["tasks"]["ready"], [])
        self.assertEqual(payload["tasks"]["implementing"], [])
        self.assertFalse(payload["coverage"]["can_replace_manual_active_work"])
        cache._validate_cached_payload(payload, REPOSITORY)

    def test_isolated_m3_authority_switch_and_rollback(self):
        live = live_projection(machine_task_count=2, coverage_complete=True)
        live["task_records"] = [
            {
                "issue_number": number, "title": f"Task {number}",
                "url": f"https://github.com/kinoko34077/demo/issues/{number}",
                "source_kind": "MACHINE", "record_role": "TASK",
                "type": "FEATURE", "work_status": status,
                "attention_disposition": None,
            }
            for number, status in ((1, "AWAITING_REVIEW"), (2, "BLOCKED"))
        ]
        payload = cache.build_cached_projection(
            REPOSITORY, live, generated_at=GENERATED_AT,
            control_trust=verified_control_trust(),
        )
        manual = ("manual issue #99",)
        params = dict(now=GENERATED_AT, manual_active_work=manual,
                      manual_next_action="Human approval required")
        exercise = cache.simulate_m3_authority_transition
        self.assertEqual(exercise(payload, **params)["authority"], "MANUAL")
        active = exercise(payload, test_admission=True, consumers_agree=True, **params)
        self.assertEqual(active["authority"], "MACHINE_TEST_ONLY")
        self.assertEqual(active["active_work"], [
            "https://github.com/kinoko34077/demo/issues/1",
            "https://github.com/kinoko34077/demo/issues/2",
        ])
        self.assertEqual(active["next_action"], "Human approval required")
        canonical_urls = tuple(active["active_work"])
        parity = exercise(payload, test_admission=True, consumers_agree=True,
                          consumer_task_urls=canonical_urls, **params)
        self.assertEqual(parity["authority"], "MACHINE_TEST_ONLY")
        for consumer_urls in (
            canonical_urls[:1],
            canonical_urls + ("https://github.com/kinoko34077/demo/issues/999",),
            canonical_urls + canonical_urls[:1],
        ):
            mismatch = exercise(payload, test_admission=True, consumers_agree=True,
                                consumer_task_urls=consumer_urls, **params)
            self.assertEqual(mismatch["authority"], "MANUAL")
            self.assertEqual(mismatch["reason"], "CONSUMER_ISSUE_REFS_DISAGREE")
            self.assertEqual(mismatch["active_work"], list(manual))
        self.assertFalse(payload["coverage"]["can_replace_manual_active_work"])
        self.assertEqual(exercise(payload, test_admission=True, **params)["authority"], "MANUAL")
        for unavailable in (None, {}, {"repository": REPOSITORY}):
            self.assertEqual(exercise(unavailable, test_admission=True,
                                      consumers_agree=True, **params)["authority"], "MANUAL")
        incomplete = cache.build_cached_projection(
            REPOSITORY, live_projection(machine_task_count=0, coverage_complete=False),
            generated_at=GENERATED_AT, control_trust=verified_control_trust(),
        )
        self.assertEqual(exercise(incomplete, test_admission=True,
                                 consumers_agree=True, **params)["authority"], "MANUAL")
        stale = dict(params, now="2026-10-06T05:50:00Z")
        self.assertEqual(exercise(payload, test_admission=True,
                                 consumers_agree=True, **stale)["authority"], "MANUAL")
        self.assertEqual(exercise(payload, test_admission=True,
                                 consumers_agree=False, **params)["active_work"], list(manual))
        recovered = exercise(payload, test_admission=True, consumers_agree=True, **params)
        self.assertEqual(recovered["authority"], "MACHINE_TEST_ONLY")
        self.assertEqual(manual, ("manual issue #99",))

    def test_all_state_preview_never_silently_truncates_or_forges_completeness(self):
        live = live_projection(machine_task_count=21, coverage_complete=True)
        live["open_issue_count"] = 21
        live["task_records"] = [
            {
                "issue_number": index, "title": f"Task {index}",
                "url": f"https://github.com/kinoko34077/demo/issues/{index}",
                "source_kind": "MACHINE", "record_role": "TASK",
                "type": "BUG", "work_status": "IMPLEMENTING",
                "attention_disposition": None,
            }
            for index in range(1, 22)
        ]
        payload = cache.build_cached_projection(
            REPOSITORY, live, generated_at=GENERATED_AT,
            control_trust=verified_control_trust(),
        )
        self.assertEqual(payload["all_state_tasks"]["status"], "TRUNCATED")
        self.assertEqual(payload["all_state_tasks"]["total"], 21)
        self.assertEqual(
            len(payload["all_state_tasks"]["records"]),
            cache.MAX_ALL_STATE_TASK_RECORDS,
        )
        cache._validate_cached_payload(payload, REPOSITORY)
        malicious = copy.deepcopy(payload)
        malicious["all_state_tasks"]["status"] = "COMPLETE"
        malicious = cache.recompute_generation_id(malicious)
        with self.assertRaises(cache.RepositoryProjectionCacheError):
            cache._validate_cached_payload(malicious, REPOSITORY)

    def test_all_state_preview_unknown_on_source_mismatch_and_old_cache_valid(self):
        live = live_projection(machine_task_count=1, coverage_complete=True)
        payload = cache.build_cached_projection(
            REPOSITORY, live, generated_at=GENERATED_AT,
            control_trust=verified_control_trust(),
        )
        self.assertEqual(payload["all_state_tasks"]["status"], "INCOMPLETE")
        self.assertEqual(payload["all_state_tasks"]["total"], 1)
        cache._validate_cached_payload(payload, REPOSITORY)
        historical = copy.deepcopy(payload)
        del historical["all_state_tasks"]
        historical = cache.recompute_generation_id(historical)
        cache._validate_cached_payload(historical, REPOSITORY)

        unavailable = cache.build_cached_projection(
            REPOSITORY,
            live_projection(source_status="UNAVAILABLE", source_freshness="UNKNOWN"),
            generated_at=GENERATED_AT, control_trust=verified_control_trust(),
        )
        self.assertEqual(unavailable["all_state_tasks"]["status"], "UNAVAILABLE")
        self.assertEqual(unavailable["all_state_tasks"]["records"], [])
        cache._validate_cached_payload(unavailable, REPOSITORY)

    def test_all_state_preview_rejects_non_task_and_duplicate(self):
        live = live_projection(machine_task_count=1, coverage_complete=True)
        good = {
            "issue_number": 1, "title": "Real task",
            "url": "https://github.com/kinoko34077/demo/issues/1",
            "source_kind": "MACHINE", "record_role": "TASK",
            "type": "FEATURE", "work_status": "AWAITING_REVIEW",
            "attention_disposition": None,
        }
        for bad_records in (
            [{**good, "record_role": "REFERENCE"}],
            [good, good],
        ):
            with self.subTest(records=bad_records):
                live["task_records"] = bad_records
                with self.assertRaises(cache.RepositoryProjectionCacheError):
                    cache.build_cached_projection(
                        REPOSITORY, live, generated_at=GENERATED_AT,
                        control_trust=verified_control_trust(),
                    )

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

    def test_replacement_migrates_exact_legacy_v1_missing_valid_until(self):
        human = (
            "## Repository\n\n`kinoko34077/demo`\n\n"
            "## Active Work\n\nHuman-owned prose.\n"
        )
        legacy = copy.deepcopy(self._payload())
        # Genuine pre-valid_until legacy had no later optional all-state field.
        legacy.pop("all_state_tasks", None)
        legacy.pop("valid_until")
        legacy = cache.recompute_generation_id(legacy)
        legacy_block = (
            cache.CACHE_MARKER_BEGIN
            + "\n"
            + json.dumps(legacy, indent=2, sort_keys=True)
            + "\n"
            + cache.CACHE_MARKER_END
        )
        body = human.rstrip() + "\n\n" + legacy_block

        updated = cache.replace_cached_projection(
            body,
            REPOSITORY,
            self._payload(),
            expected_body_sha256=maintenance_sync_check.canonical_body_sha256(body),
        )

        parsed = cache.parse_cached_projection(updated, REPOSITORY)
        self.assertIsNotNone(parsed)
        self.assertIn("valid_until", parsed.payload)
        self.assertTrue(updated.startswith(human.rstrip()))
        self.assertIn("Human-owned prose.", updated)

    def test_replacement_rejects_corrupt_legacy_v1_generation(self):
        legacy = copy.deepcopy(self._payload())
        # Genuine pre-valid_until legacy had no later optional all-state field.
        legacy.pop("all_state_tasks", None)
        legacy.pop("valid_until")
        legacy = cache.recompute_generation_id(legacy)
        legacy["generation_id"] = "sha256:" + ("0" * 64)
        body = (
            "## Repository\n\n`kinoko34077/demo`\n\n"
            + cache.CACHE_MARKER_BEGIN
            + "\n"
            + json.dumps(legacy, indent=2, sort_keys=True)
            + "\n"
            + cache.CACHE_MARKER_END
        )

        with self.assertRaisesRegex(
            cache.RepositoryProjectionCacheError,
            "legacy generation_id",
        ):
            cache.replace_cached_projection(
                body,
                REPOSITORY,
                self._payload(),
                expected_body_sha256=maintenance_sync_check.canonical_body_sha256(body),
            )

    def test_replacement_rejects_legacy_v1_with_additional_missing_field(self):
        legacy = copy.deepcopy(self._payload())
        # Genuine pre-valid_until legacy had no later optional all-state field.
        legacy.pop("all_state_tasks", None)
        legacy.pop("valid_until")
        legacy.pop("coverage")
        legacy = cache.recompute_generation_id(legacy)
        body = (
            "## Repository\n\n`kinoko34077/demo`\n\n"
            + cache.CACHE_MARKER_BEGIN
            + "\n"
            + json.dumps(legacy, indent=2, sort_keys=True)
            + "\n"
            + cache.CACHE_MARKER_END
        )

        with self.assertRaisesRegex(
            cache.RepositoryProjectionCacheError,
            "legacy repository projection cache missing fields",
        ):
            cache.replace_cached_projection(
                body,
                REPOSITORY,
                self._payload(),
                expected_body_sha256=maintenance_sync_check.canonical_body_sha256(body),
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
