import unittest

from tools import reconciliation_publication as rp


HEAD = "a" * 40
DIGEST = "sha256:" + "c" * 64


def reviewer(**overrides):
    data = {
        "contract_version": "development-reconciliation.v1",
        "task_ref": "owner/repository#7",
        "task_body_sha256": DIGEST,
        "entry_ref": "https://github.com/owner/repository/issues/7",
        "observed_at": "2026-09-28T05:00:00Z",
        "reason_codes": ["DIFFERENT_REVIEWER_REQUIRED"],
        "human_gate": False,
        "evidence_complete": True,
        "disposition": "NEEDS_REVIEWER",
        "different_reviewer_required": True,
        "pr_number": 12,
        "pr_head_sha": HEAD,
        "scope": "Review PR #12 at exact head",
    }
    data.update(overrides)
    return data


class ReconciliationPublicationValidationTests(unittest.TestCase):
    def test_observed_at_requires_timezone_aware_rfc3339_timestamp(self):
        with self.assertRaises(ValueError):
            rp.build_publication(reviewer(observed_at="2026-09-28T05:00:00"))

    def test_human_gate_must_be_boolean(self):
        with self.assertRaises(ValueError):
            rp.build_publication(reviewer(human_gate="no"))


if __name__ == "__main__":
    unittest.main()
