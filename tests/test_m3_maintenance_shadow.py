"""M3 Maintenance consumer shadow: no authority or runtime classifier changes."""
import copy
import unittest

from tools import maintenance_github as mg
from tools import maintenance_audit as ma


REPOSITORY = "kinoko34077/testapp"
CONTROL_REF = "kinoko34077/devflow#32"
CONTROL_URL = "https://github.com/kinoko34077/devflow/issues/32"
OWNER_REF = "kinoko34077/testapp#30"
ACTIVE = "kinoko34077/testapp#30"
NEXT = "`[WAIT] Retain Human policy and manual routing.`"


def task(number=30, status="AWAITING_REVIEW"):
    return {
        "issue_number": number,
        "record_role": "TASK",
        "source_kind": "MACHINE",
        "work_status": status,
        "url": f"https://github.com/{REPOSITORY}/issues/{number}",
    }


def view(*records):
    return {
        "repository": REPOSITORY,
        "control_ref": CONTROL_URL,
        "source_status": "AVAILABLE",
        "source_freshness": "CURRENT",
        "source_error": None,
        "coverage_status": "COMPLETE",
        "view_mode": "MACHINE_COMPLETE_SHADOW",
        "can_replace_manual_active_work": False,
        "machine_task_count": len(records),
        "legacy_hint_count": 0,
        "unclassified_count": 0,
        "invalid_metadata_count": 0,
        "untrusted_metadata_count": 0,
        "manual_control": {"active_work": ACTIVE, "next_action": NEXT},
        "task_records": list(records),
    }


def shadow(work_view, manual_owner_ref=OWNER_REF, *, trusted=True, source_status="OK"):
    return mg._m3_owner_shadow(
        work_view,
        repository=REPOSITORY,
        control_ref=CONTROL_REF,
        sections={"Active Work": ACTIVE, "Next Action": NEXT},
        trusted=trusted,
        source_status=source_status,
        manual_owner_ref=manual_owner_ref,
    )


class M3OwnerShadowTests(unittest.TestCase):
    def test_review_and_blocked_are_retained_without_runtime_authority(self):
        for state in ("READY_FOR_IMPLEMENTATION", "IMPLEMENTING", "AWAITING_REVIEW", "BLOCKED", "DONE"):
            with self.subTest(state=state):
                result = shadow(view(task(status=state)))
                self.assertEqual(result["status"], "MATCHED_SHADOW")
                self.assertEqual(result["machine_task_refs"], [OWNER_REF])
                self.assertFalse(result["can_replace_manual_active_work"])

    def test_multiple_full_state_tasks_never_become_one_maintenance_owner(self):
        result = shadow(view(task(), task(31, "BLOCKED")))
        self.assertEqual(result["status"], "MULTIPLE_TASKS_SHADOW")
        self.assertEqual(result["reason"], "ONE_OWNER_CONTRACT_INSUFFICIENT")
        self.assertEqual(result["machine_task_refs"], [OWNER_REF, f"{REPOSITORY}#31"])
        self.assertFalse(result["can_replace_manual_active_work"])

    def test_empty_true_complete_is_not_a_nonempty_cutover_proof(self):
        result = shadow(view(), manual_owner_ref=None)
        self.assertEqual(result["status"], "MATCHED_EMPTY_SHADOW")
        self.assertFalse(result["can_replace_manual_active_work"])

    def test_stale_manual_owner_is_only_diagnostic(self):
        result = shadow(view(task(31)))
        self.assertEqual(result["status"], "DIVERGENT_SHADOW")
        self.assertEqual(result["manual_owner_ref"], OWNER_REF)
        self.assertFalse(result["can_replace_manual_active_work"])

    def test_all_unsafe_coverage_and_integrity_cases_fallback(self):
        good = view(task())
        mutations = [
            ("repository", "other/repo"),
            ("control_ref", "https://github.com/kinoko34077/devflow/issues/31"),
            ("source_status", "UNAVAILABLE"),
            ("source_freshness", "STALE"),
            ("source_error", "transport unavailable"),
            ("coverage_status", "INCOMPLETE"),
            ("view_mode", "MANUAL_CONTROL_FALLBACK"),
            ("can_replace_manual_active_work", True),
            ("legacy_hint_count", 1),
            ("unclassified_count", 1),
            ("invalid_metadata_count", 1),
            ("untrusted_metadata_count", 1),
            ("machine_task_count", 2),
            ("machine_task_count", True),
            ("task_records", []),
            ("task_records", [task(), task()]),
            ("task_records", [dict(task(), record_role="TRACKER")]),
            ("task_records", [dict(task(), source_kind="LEGACY")]),
            ("task_records", [dict(task(), url="https://github.com/evil/repo/issues/30")]),
            ("manual_control", {"active_work": "different", "next_action": NEXT}),
        ]
        for key, value in mutations:
            with self.subTest(field=key, value=str(value)[:40]):
                bad = copy.deepcopy(good)
                bad[key] = value
                out = shadow(bad)
                self.assertEqual(out["status"], "MANUAL_CONTROL_FALLBACK")
                self.assertFalse(out["can_replace_manual_active_work"])
        for bad in (None, {}, [], "not a view"):
            self.assertEqual(shadow(bad)["status"], "MANUAL_CONTROL_FALLBACK")
        self.assertEqual(shadow(good, trusted=False)["status"], "MANUAL_CONTROL_FALLBACK")
        self.assertEqual(shadow(good, source_status="UNAVAILABLE")["status"], "MANUAL_CONTROL_FALLBACK")

    def test_default_collector_and_classifier_unchanged_and_opt_in_is_diagnostic(self):
        body = (
            f"## Repository\n\n`{REPOSITORY}`\n\n"
            "## Work Status\n\n`AWAITING_REVIEW`\n\n"
            f"## Active Work\n\n{ACTIVE}\n\n"
            f"## Next Action\n\n{NEXT}\n\n"
        )

        class Transport:
            def __init__(self):
                self.paths = []

            def get_json(self, path):
                self.paths.append(path)
                if path.endswith("/issues/32"):
                    return {
                        "number": 32, "title": "[REPO] testapp", "state": "open",
                        "html_url": CONTROL_URL, "body": body,
                        "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-10-12T07:00:00Z",
                    }
                if path.endswith("/issues/30"):
                    return {
                        "number": 30, "title": "M3 real task", "state": "open",
                        "html_url": f"https://github.com/{REPOSITORY}/issues/30",
                        "body": "## Work Status\n\n`AWAITING_REVIEW`\n",
                        "author_association": "OWNER",
                        "user": {"id": 79015263, "login": "kinoko34077"},
                        "updated_at": "2026-10-12T07:00:00Z",
                    }
                raise AssertionError(path)

        no_shadow = mg.collect_repository(Transport(), REPOSITORY, CONTROL_REF, "2026-10-12T07:01:00Z")
        self.assertNotIn("m3_shadow", no_shadow)
        baseline = ma.classify_repository(no_shadow)
        transport = Transport()
        with_shadow = mg.collect_repository(
            transport, REPOSITORY, CONTROL_REF, "2026-10-12T07:01:00Z",
            m3_work_view=view(task()),
        )
        self.assertEqual(with_shadow["m3_shadow"]["status"], "MATCHED_SHADOW")
        self.assertEqual(transport.paths, [
            "/repos/kinoko34077/devflow/issues/32", "/repos/kinoko34077/testapp/issues/30",
        ])
        with_shadow.pop("m3_shadow")
        self.assertEqual(no_shadow, with_shadow)
        self.assertEqual(ma.classify_repository(with_shadow), baseline)

    def test_mismatched_optional_view_does_not_change_maintenance_result(self):
        control = (
            f"## Repository\n\n`{REPOSITORY}`\n\n"
            "## Work Status\n\n`AUDITED`\n\n"
            "## Active Work\n\nNo active repository-local implementation owner.\n\n"
            f"## Next Action\n\n{NEXT}\n"
        )
        class Transport:
            def get_json(self, path):
                if path.endswith("/issues/32"):
                    return {"number": 32, "title": "[REPO] testapp", "state": "open",
                            "html_url": CONTROL_URL, "author_association": "OWNER",
                            "user": {"id": 79015263, "login": "kinoko34077"},
                            "body": control, "updated_at": "2026-10-12T07:00:00Z"}
                raise AssertionError(path)
        out = mg.collect_repository(Transport(), REPOSITORY, CONTROL_REF,
                                    "2026-10-12T07:01:00Z", m3_work_view=view(task()))
        self.assertEqual(out["m3_shadow"]["status"], "MANUAL_CONTROL_FALLBACK")
        self.assertEqual(ma.classify_repository(out)["disposition"], "NO_ACTION")


if __name__ == "__main__":
    unittest.main()
