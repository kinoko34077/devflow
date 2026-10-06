import copy
import unittest

from tools import human_portfolio_cache as cache
from tools import repository_projection_cache


REPOSITORY = "kinoko34077/demo"
OBSERVED_AT = "2026-10-06T00:10:00Z"
GENERATED_AT = "2026-10-06T00:11:00Z"


def live_read():
    return {
        "schema_version": "human-portfolio-read.v1",
        "repository": REPOSITORY,
        "observed_at": OBSERVED_AT,
        "complete": True,
        "repository_source": {
            "status": "AVAILABLE",
            "freshness": "CURRENT",
            "error": None,
        },
        "reconciliation_source": {
            "status": "AVAILABLE",
            "trust": "VERIFIED",
            "control_issue_number": 7,
            "control_url": "https://github.com/kinoko34077/devflow/issues/7",
            "error": None,
            "task_errors": [],
        },
        "entries": [
            {
                "repository": REPOSITORY,
                "task_ref": REPOSITORY + "#11",
                "entry_ref": "https://github.com/kinoko34077/demo/issues/11",
                "disposition": "READY",
                "role": "implementer",
                "source_kind": "REPOSITORY_PROJECTION",
                "observed_at": OBSERVED_AT,
                "work_status": "READY_FOR_IMPLEMENTATION",
                "publication_id": None,
                "evidence_freshness": "CURRENT",
                "evidence_trust": "VERIFIED",
            },
            {
                "repository": REPOSITORY,
                "task_ref": REPOSITORY + "#12",
                "entry_ref": "https://github.com/kinoko34077/demo/issues/12",
                "disposition": "NEEDS_REVIEWER",
                "role": "reviewer",
                "source_kind": "RECONCILIATION",
                "observed_at": OBSERVED_AT,
                "work_status": None,
                "publication_id": "sha256:" + ("a" * 64),
                "evidence_freshness": "CURRENT",
                "evidence_trust": "VERIFIED",
            },
        ],
    }


class HumanPortfolioCacheTests(unittest.TestCase):
    def _payload(self):
        return cache.build_cached_human_portfolio(
            REPOSITORY,
            live_read(),
            generated_at=GENERATED_AT,
        )

    def test_build_parse_and_current_freshness_preserve_live_observation(self):
        payload = self._payload()
        self.assertEqual("human-portfolio-cache.v1", payload["schema_version"])
        self.assertEqual(OBSERVED_AT, payload["observed_at"])
        self.assertEqual(GENERATED_AT, payload["generated_at"])
        self.assertEqual("2026-10-07T00:11:00Z", payload["valid_until"])
        self.assertTrue(payload["complete"])

        block = cache.render_cached_human_portfolio(payload)
        parsed = cache.parse_cached_human_portfolio(block, REPOSITORY)
        self.assertIsNotNone(parsed)
        self.assertEqual(payload, parsed.payload)
        self.assertEqual(
            "CURRENT",
            cache.effective_cache_freshness(
                payload,
                now="2026-10-06T12:00:00Z",
            ),
        )

    def test_generation_time_never_precedes_live_observation(self):
        payload = cache.build_cached_human_portfolio(
            REPOSITORY,
            live_read(),
            generated_at="2026-10-05T23:00:00Z",
        )
        self.assertEqual(OBSERVED_AT, payload["generated_at"])
        self.assertEqual("2026-10-07T00:10:00Z", payload["valid_until"])

    def test_ttl_and_source_state_fail_closed(self):
        payload = self._payload()
        self.assertEqual(
            "UNKNOWN",
            cache.effective_cache_freshness(
                payload,
                now="2026-10-05T23:59:00Z",
            ),
        )
        self.assertEqual(
            "STALE",
            cache.effective_cache_freshness(
                payload,
                now="2026-10-07T00:11:01Z",
            ),
        )

        unavailable = live_read()
        unavailable["repository_source"] = {
            "status": "UNAVAILABLE",
            "freshness": "UNKNOWN",
            "error": "read failed",
        }
        unavailable["complete"] = False
        unavailable["entries"] = []
        unavailable_payload = cache.build_cached_human_portfolio(
            REPOSITORY,
            unavailable,
            generated_at=GENERATED_AT,
        )
        self.assertEqual(
            "UNAVAILABLE",
            cache.effective_cache_freshness(
                unavailable_payload,
                now="2026-10-06T12:00:00Z",
            ),
        )

        invalid = live_read()
        invalid["reconciliation_source"] = {
            "status": "INVALID",
            "trust": "UNKNOWN",
            "control_issue_number": 7,
            "control_url": "https://github.com/kinoko34077/devflow/issues/7",
            "error": "malformed publication",
            "task_errors": [],
        }
        invalid["complete"] = False
        invalid["entries"] = invalid["entries"][:1]
        invalid_payload = cache.build_cached_human_portfolio(
            REPOSITORY,
            invalid,
            generated_at=GENERATED_AT,
        )
        self.assertEqual(
            "INVALID",
            cache.effective_cache_freshness(
                invalid_payload,
                now="2026-10-06T12:00:00Z",
            ),
        )

    def test_generation_tamper_and_unknown_fields_fail_closed(self):
        payload = self._payload()
        tampered = copy.deepcopy(payload)
        tampered["complete"] = False
        with self.assertRaisesRegex(cache.HumanPortfolioCacheError, "generation_id"):
            cache.parse_cached_human_portfolio(
                cache.CACHE_MARKER_BEGIN
                + "\n"
                + __import__("json").dumps(tampered)
                + "\n"
                + cache.CACHE_MARKER_END,
                REPOSITORY,
            )

        unknown = copy.deepcopy(payload)
        unknown["surprise"] = True
        unknown = cache.recompute_generation_id(unknown)
        with self.assertRaisesRegex(cache.HumanPortfolioCacheError, "unknown fields"):
            cache.render_cached_human_portfolio(unknown)

    def test_entry_ref_must_identify_exact_owning_task(self):
        value = live_read()
        value["entries"][0]["entry_ref"] = (
            "https://github.com/kinoko34077/other/issues/11"
        )
        with self.assertRaisesRegex(
            cache.HumanPortfolioCacheError,
            "exact owning task",
        ):
            cache.build_cached_human_portfolio(
                REPOSITORY,
                value,
                generated_at=GENERATED_AT,
            )

        value = live_read()
        value["entries"][0]["entry_ref"] = (
            "https://github.com/kinoko34077/demo/issues/99"
        )
        with self.assertRaisesRegex(
            cache.HumanPortfolioCacheError,
            "exact owning task",
        ):
            cache.build_cached_human_portfolio(
                REPOSITORY,
                value,
                generated_at=GENERATED_AT,
            )

    def test_reconciliation_publication_id_is_canonical_sha256(self):
        value = live_read()
        value["entries"][1]["publication_id"] = "not-a-digest"
        with self.assertRaisesRegex(
            cache.HumanPortfolioCacheError,
            "publication_id",
        ):
            cache.build_cached_human_portfolio(
                REPOSITORY,
                value,
                generated_at=GENERATED_AT,
            )

    def test_marker_replacement_preserves_human_text_and_projection_marker(self):
        projection_payload = {
            "schema_version": repository_projection_cache.CACHE_SCHEMA_VERSION,
            "repository": REPOSITORY,
            "generated_at": "2026-10-06T00:11:00Z",
            "valid_until": "2026-10-07T00:11:00Z",
            "generation_id": "",
            "source": {
                "status": "AVAILABLE",
                "freshness": "CURRENT",
                "observed_at": OBSERVED_AT,
                "error": None,
                "digest": "sha256:" + ("1" * 64),
            },
            "coverage": {
                "status": "INCOMPLETE",
                "ambiguous": True,
                "active_work_evidence": "NO_MACHINE_TASK_EVIDENCE",
                "can_replace_manual_active_work": False,
            },
            "counts": {
                "open_issues": 0,
                "machine_records": 0,
                "machine_tasks": 0,
                "legacy_hints": 0,
                "unclassified": 0,
                "invalid_metadata": 0,
                "untrusted_metadata": 0,
            },
            "type_counts": {"machine": {}, "legacy_hint": {}},
            "tasks": {"ready": [], "implementing": []},
            "references": {
                "newest_open_issue": None,
                "recently_active_issue": None,
            },
            "control_trust": {
                "status": "VERIFIED",
                "freshness": "CURRENT",
                "source": repository_projection_cache.CONTROL_TRUST_SOURCE,
                "observed_at": OBSERVED_AT,
                "detail": None,
            },
        }
        projection_payload = repository_projection_cache.recompute_generation_id(
            projection_payload
        )
        body = (
            "## Repository\n\nkinoko34077/demo\n\nHuman-owned prose.\n\n"
            + repository_projection_cache.render_cached_projection(projection_payload)
        )
        updated = cache.replace_cached_human_portfolio(
            body,
            REPOSITORY,
            self._payload(),
        )
        self.assertIn("Human-owned prose.", updated)
        self.assertIn(repository_projection_cache.CACHE_MARKER_BEGIN, updated)
        self.assertIn(cache.CACHE_MARKER_BEGIN, updated)
        parsed_projection = repository_projection_cache.parse_cached_projection(
            updated,
            REPOSITORY,
        )
        self.assertEqual(
            projection_payload["generation_id"],
            parsed_projection.payload["generation_id"],
        )

    def test_corrupt_existing_human_marker_is_not_silently_overwritten(self):
        body = (
            "## Repository\n\nkinoko34077/demo\n\n"
            + cache.CACHE_MARKER_BEGIN
            + "\n{not-json}\n"
            + cache.CACHE_MARKER_END
        )
        with self.assertRaises(cache.HumanPortfolioCacheError):
            cache.replace_cached_human_portfolio(
                body,
                REPOSITORY,
                self._payload(),
            )


if __name__ == "__main__":
    unittest.main()
