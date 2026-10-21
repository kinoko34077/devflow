"""Offline regression tests for the fixed native PR semantic pilot (#726)."""
import json
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

from tools import control_semantic_pilot as pilot


def issue(body=None, **changes):
    if body is None:
        body = (
            "## Active Work\n- unrelated\n\n## Next Action\n\n"
            "- Actual [PR #14](https://github.com/kinoko34077/"
            "kinotch-editor-platform/pull/14) is **MERGED** "
            "(head source verified). No product acceptance.\n"
            "- [PR #15](https://github.com/kinoko34077/"
            "kinotch-editor-platform/pull/15) remains independently pending.\n"
            "\n## Canonical Entry Points\nREADME.md\n"
        )
    payload = {
        "number": 705, "title": "[REPO] kinotch-editor-platform",
        "state": "open",
        "html_url": pilot.CONTROL_URL, "body": body,
    }
    payload.update(changes)
    return payload


def pr(**changes):
    payload = {
        "number": 14,
        "html_url": pilot.PR_URL,
        "state": "closed",
        "merged_at": "2026-10-20T12:00:00Z",
        "merged": True,
        "head": {"sha": "a" * 40},
        "base": {"repo": {"full_name": pilot.REPOSITORY}},
    }
    payload.update(changes)
    return payload


class PilotTests(TestCase):
    def check(self, expected, control=None, pull=None, **runner_changes):
        control = issue() if control is None else control
        pull = pr() if pull is None else pull
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args, kwargs))
            out = control if len(calls) == 1 else pull
            return SimpleNamespace(
                stdout=runner_changes.get("stdout", json.dumps(out).encode()),
                returncode=runner_changes.get("returncode", 0), stderr=b"",
            )

        with patch.object(pilot.subprocess, "run", side_effect=fake_run):
            answer = pilot.check_editor_pr14_once()
        self.assertEqual(answer["status"], expected)
        self.assertLessEqual(len(calls), 2)
        for args, kwargs in calls:
            self.assertEqual(args[:4], ["gh", "api", "--method", "GET"])
            self.assertIn(args[4], (pilot.CONTROL_PATH, pilot.PR_PATH))
            self.assertFalse(kwargs.get("shell", False))
            self.assertEqual(kwargs["timeout"], 12)
        return answer, calls

    def test_real_shape_aligned(self):
        result, calls = self.check("ALIGNED")
        self.assertEqual(result["observed_stage"], "MERGED")
        self.assertEqual(result["pr_head_sha"], "a" * 40)
        self.assertEqual(
            [item[0][-1] for item in calls],
            [pilot.CONTROL_PATH, pilot.PR_PATH],
        )

    def test_stale_review_claim_is_detected_without_writing(self):
        stale = issue(body=issue()["body"].replace(
            "is **MERGED**", "is **AWAIT_REVIEW**"
        ))
        result, _ = self.check("POTENTIAL_MISMATCH", control=stale)
        self.assertEqual(result["observed_stage"], "MERGED")

    def test_no_nlp_guess_from_loose_prose(self):
        unclear = issue(body=issue()["body"].replace(
            "is **MERGED**", "appears merged"
        ))
        self.check("UNKNOWN", control=unclear)

    def test_historical_statement_cannot_override_current(self):
        body = (
            "## Next Action\n"
            "**HISTORICAL OLD ACTION**\n"
            + issue()["body"].split("## Next Action\n")[1].split(
                "## Canonical Entry Points"
            )[0]
            + "## Canonical Entry Points\n"
        )
        self.check("UNKNOWN", control=issue(body=body))

    def test_multiple_competing_claims_fail_closed(self):
        base = issue()["body"]
        line = base.split("- Actual ")[1].split("\n")[0]
        duplicated = base.replace(
            "- Actual " + line, "- Actual " + line + "\n- Actual " + line
        )
        self.check("UNKNOWN", control=issue(body=duplicated))

    def test_control_not_current_or_wrong_owner(self):
        for changed in ({"state": "closed"}, {"title": "[REPO] other"},
                        {"html_url": "https://other.test/705"},
                        {"number": 706}, {"body": ""}):
            with self.subTest(changed=changed):
                self.check("UNKNOWN", control=issue(**changed))

    def test_pr_identity_rejected(self):
        changes = (
            {"number": 15},
            {"html_url": "https://github.com/other/pull/14"},
            {"base": {"repo": {"full_name": "other/repository"}}},
            {"head": {"sha": "not-a-sha"}},
            {"state": "wrong"},
            {"merged_at": ""},
        )
        for changed in changes:
            with self.subTest(changed=changed):
                self.check("UNKNOWN", pull=pr(**changed))

    def test_closed_unmerged_is_specific_negative_stage(self):
        doc = issue(body=issue()["body"].replace(
            "is **MERGED**", "is **CLOSED_UNMERGED**"
        ))
        answer, _ = self.check(
            "ALIGNED", control=doc, pull=pr(
                state="closed", merged=False, merged_at=None
            )
        )
        self.assertEqual(answer["observed_stage"], "CLOSED_UNMERGED")

    def test_open_pr_is_not_a_merge_and_does_not_prove_review_ready(self):
        result, _ = self.check(
            "POTENTIAL_MISMATCH", pull=pr(
                state="open", merged=False, merged_at=None
            )
        )
        self.assertEqual(result["observed_stage"], "OPEN")
        self.assertNotIn("READY", result["observed_stage"])

    def test_http_failure_does_not_emit_false_mismatch(self):
        self.check("UNKNOWN", returncode=1)

    def test_malformed_response_does_not_emit_false_mismatch(self):
        self.check("UNKNOWN", stdout=b"{bad json")

    def test_auth_and_timeout_fail_closed(self):
        for exception in (OSError("no gh"), pilot.subprocess.TimeoutExpired("gh", 12)):
            with self.subTest(exception=repr(exception)):
                with patch.object(pilot.subprocess, "run", side_effect=exception):
                    self.assertEqual(
                        pilot.check_editor_pr14_once()["status"], "UNKNOWN"
                    )

    def test_output_never_contains_raw_issue_text_or_secret(self):
        document = issue()
        document["body"] += "\nSecret marker should never be returned: ghp_fixture_only"
        result, _ = self.check("ALIGNED", control=document)
        self.assertNotIn("ghp_fixture_only", repr(result))
        self.assertEqual(set(result), {
            "status", "reason", "subject", "claimed_stage",
            "observed_stage", "pr_head_sha", "control_read_at",
            "pr_read_at", "control_url", "pr_url",
        })

    def test_reject_non_dict_api_shape(self):
        with patch.object(
            pilot.subprocess, "run",
            return_value=SimpleNamespace(stdout=b"[]", returncode=0),
        ):
            self.assertEqual(pilot.check_editor_pr14_once()["status"], "UNKNOWN")


    def test_explicit_second_pr_current_open_is_aligned(self):
        # One opted-in Control, two distinct PR subjects; not a repo crawl.
        doc = issue(body=issue()["body"].replace(
            "- [PR #15](https://github.com/kinoko34077/"
            "kinotch-editor-platform/pull/15) remains independently pending.",
            "- [PR #15](https://github.com/kinoko34077/"
            "kinotch-editor-platform/pull/15) is "
            "**OPEN, READY (not Draft), base main** — unrelated review scope.",
        ))
        second = pr(
            number=15,
            html_url="https://github.com/kinoko34077/kinotch-editor-platform/pull/15",
            state="open", merged=False, merged_at=None,
        )
        seen = []

        def provider(args, **kw):
            seen.append(args[-1])
            return SimpleNamespace(
                stdout=json.dumps(doc if len(seen) == 1 else second).encode(),
                returncode=0, stderr=b"",
            )

        with patch.object(pilot.subprocess, "run", side_effect=provider):
            result = pilot.check_pr_transition_once(
                705, "kinoko34077/kinotch-editor-platform", 15
            )
        self.assertEqual(result["status"], "ALIGNED")
        self.assertEqual(result["claimed_stage"], "OPEN")
        self.assertEqual(result["observed_stage"], "OPEN")
        self.assertEqual(seen, [
            "repos/kinoko34077/devflow/issues/705",
            "repos/kinoko34077/kinotch-editor-platform/pulls/15",
        ])

    def test_subsequent_merge_with_stale_open_claim_is_mismatch(self):
        doc = issue(body=(
            "## Next Action\n- [PR #15]"
            "(https://github.com/kinoko34077/kinotch-editor-platform/pull/15)"
            " is **OPEN** — still under review.\n## Canonical Entry Points\n"
        ))
        merged = pr(
            number=15,
            html_url="https://github.com/kinoko34077/kinotch-editor-platform/pull/15",
            merged=True, merged_at="2026-10-22T00:00:00Z",
        )
        docs = [doc, merged]

        def provider(args, **kw):
            return SimpleNamespace(
                stdout=json.dumps(docs.pop(0)).encode(),
                returncode=0, stderr=b"",
            )

        with patch.object(pilot.subprocess, "run", side_effect=provider):
            result = pilot.check_pr_transition_once(
                705, "kinoko34077/kinotch-editor-platform", 15
            )
        self.assertEqual(result["status"], "POTENTIAL_MISMATCH")
        self.assertEqual((result["claimed_stage"], result["observed_stage"]),
                         ("OPEN", "MERGED"))

    def test_invalid_or_cross_owner_input_does_not_invoke_network(self):
        for args in (
            (True, pilot.REPOSITORY, 14),
            (705, pilot.REPOSITORY, 0),
            (705, "someoneelse/repo", 14),
            (705, "kinoko34077/repo/../../other", 14),
            (705, "kinoko34077/repo..other", 14),
            (705, pilot.REPOSITORY, True),
        ):
            with self.subTest(args=args):
                with patch.object(
                    pilot.subprocess, "run",
                    side_effect=AssertionError("network called"),
                ):
                    self.assertEqual(
                        pilot.check_pr_transition_once(*args)["status"], "UNKNOWN"
                    )

    def test_open_claim_not_review_readiness(self):
        doc = issue(body=issue()["body"].replace(
            "is **MERGED**", "is **OPEN, READY (not Draft)**"
        ))
        unready = pr(state="open", merged=False, merged_at=None)
        result, _ = self.check("ALIGNED", control=doc, pull=unready)
        self.assertEqual(result["observed_stage"], "OPEN")

    def test_mismatched_pr_merge_metadata_fails_closed(self):
        self.check("UNKNOWN", pull=pr(merged=False))
        self.check("UNKNOWN", pull=pr(state="open", merged=True))
        self.check("UNKNOWN", pull=pr(
            state="closed", merged=False, merged_at="2026-10-19T00:00:00Z"
        ))

    def test_current_heading_duplicated_fails_closed(self):
        doc = issue(body=issue()["body"].replace(
            "## Canonical Entry Points", "## Next Action\nambiguous\n"
            "## Canonical Entry Points"
        ))
        self.check("UNKNOWN", control=doc)

    def test_second_pr_identity_is_not_satisfied_by_first_pr(self):
        # The first subject is MERGED; a request for #15 must not reuse it.
        with patch.object(pilot.subprocess, "run", side_effect=AssertionError(
            "expected caller-specific GET fixture"
        )):
            self.assertEqual(
                pilot.check_pr_transition_once(0, pilot.REPOSITORY, 15)["status"],
                "UNKNOWN",
            )

if __name__ == "__main__":
    main()
