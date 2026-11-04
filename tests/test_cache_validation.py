from __future__ import annotations

from datetime import datetime, timezone
import unittest

from tools.cache_validation import (
    format_timestamp,
    require_bool,
    require_exact_fields,
    require_mapping,
    require_optional_string,
    require_repository,
    require_timestamp,
    timestamp_value,
)


class CacheValidationError(ValueError):
    pass


class CacheValidationTests(unittest.TestCase):
    def test_mapping_is_copied_and_exact_fields_are_checked(self) -> None:
        value = {"ok": 1}

        copied = require_mapping(value, "payload", CacheValidationError)
        self.assertEqual(copied, value)
        self.assertIsNot(copied, value)

        require_exact_fields(copied, frozenset({"ok"}), "payload", CacheValidationError)
        with self.assertRaisesRegex(CacheValidationError, "payload missing fields: required"):
            require_exact_fields(copied, frozenset({"ok", "required"}), "payload", CacheValidationError)
        with self.assertRaisesRegex(CacheValidationError, "payload has unknown fields: extra"):
            require_exact_fields({"ok": 1, "extra": 2}, frozenset({"ok"}), "payload", CacheValidationError)

    def test_scalar_contracts_preserve_the_shared_error_type(self) -> None:
        self.assertEqual(require_repository(" owner/repo ", "repository", CacheValidationError), "owner/repo")
        self.assertTrue(require_bool(True, "complete", CacheValidationError))
        self.assertEqual(require_optional_string(" detail ", "detail", CacheValidationError), "detail")
        self.assertIsNone(require_optional_string(None, "detail", CacheValidationError))

        with self.assertRaisesRegex(CacheValidationError, "repository must be owner/repository"):
            require_repository("not a repository", "repository", CacheValidationError)
        with self.assertRaisesRegex(CacheValidationError, "complete must be boolean"):
            require_bool(1, "complete", CacheValidationError)
        with self.assertRaisesRegex(CacheValidationError, "detail must be a non-empty string or null"):
            require_optional_string(" ", "detail", CacheValidationError)

    def test_timestamp_round_trip_preserves_rfc3339_contract(self) -> None:
        value = "2026-11-04T00:00:00Z"

        self.assertEqual(require_timestamp(value, "observed_at", CacheValidationError), value)
        self.assertEqual(
            timestamp_value(value, "observed_at", CacheValidationError),
            datetime(2026, 11, 4, tzinfo=timezone.utc),
        )
        self.assertEqual(format_timestamp(datetime(2026, 11, 4, tzinfo=timezone.utc)), value)

        with self.assertRaisesRegex(CacheValidationError, "observed_at must include an RFC-3339 timezone offset"):
            require_timestamp("2026-11-04T00:00:00", "observed_at", CacheValidationError)


if __name__ == "__main__":
    unittest.main()

