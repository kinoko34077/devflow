import unittest
import json
import io
from unittest import mock

from tools import review_readiness


HEAD = "a" * 40
OTHER = "b" * 40


def pr_body(
    formal_required="yes",
    different_required="no",
    implementer_system="ChatGPT",
    implementer_model="GPT-5.6 Sol",
):
    return f"""## Review target
- Formal review required: {formal_required}
- Different reviewer required: {different_required}
- Review focus: correctness
- Reviewed-SHA target: {HEAD}

## Implementer Provenance
- Implementer-System: {implementer_system}
- Implementer-Model: {implementer_model}
"""


def review_body(
    *,
    reviewed_commit=HEAD,
    reviewer_system="ChatGPT",
    reviewer_model="GPT-5.6 Sol",
    implementer_system="ChatGPT",
    implementer_model="GPT-5.6 Sol",
    blocking="none",
    decision="COMMENT",
    version="2",
):
    return f"""## Review Result
- Blocking findings: {blocking}
- Reviewed-Commit: {reviewed_commit}

### Review Provenance
- Reviewer-System: {reviewer_system}
- Reviewer-Model: {reviewer_model}
- Implementer-System: {implementer_system}
- Implementer-Model: {implementer_model}
- Reviewed-Commit: {reviewed_commit}
- Review-Scope: test
- Decision: {decision}
- Review-Provenance-Version: {version}
"""


def pr(
    formal_required="yes",
    different_required="no",
    implementer_system="ChatGPT",
    implementer_model="GPT-5.6 Sol",
    body=None,
):
    return {
        "body": (
            pr_body(
                formal_required,
                different_required,
                implementer_system,
                implementer_model,
            )
            if body is None
            else body
        ),
        "head": {"sha": HEAD},
    }


def review(**kwargs):
    commit_id = kwargs.pop("commit_id", HEAD)
    state = kwargs.pop("state", "COMMENTED")
    review_id = kwargs.pop("review_id", 101)
    return {
        "id": review_id,
        "state": state,
        "commit_id": commit_id,
        "body": review_body(**kwargs),
    }


class ReviewReadinessTests(unittest.TestCase):
    def test_default_same_signature_formal_review_passes(self):
        result = review_readiness.evaluate(pr(), [review()])
        self.assertTrue(result.ready)
        self.assertEqual(result.matched_review_id, 101)

    def test_markdown_inline_code_reviewed_commit_passes(self):
        candidate = review()
        candidate["body"] = candidate["body"].replace(
            f"Reviewed-Commit: {HEAD}", f"Reviewed-Commit: `{HEAD}`"
        )
        result = review_readiness.evaluate(pr(), [candidate])
        self.assertTrue(result.ready)
        self.assertEqual(result.matched_review_id, 101)

    def test_default_different_signature_formal_review_passes(self):
        candidate = review(
            reviewer_system="Claude Code",
            reviewer_model="Sonnet",
        )
        result = review_readiness.evaluate(pr(), [candidate])
        self.assertTrue(result.ready)

    def test_different_reviewer_gate_rejects_same_signature(self):
        result = review_readiness.evaluate(
            pr(different_required="yes"),
            [review()],
        )
        self.assertFalse(result.ready)
        self.assertIn("different reviewer", result.reason.lower())

    def test_different_reviewer_gate_normalizes_case_and_whitespace(self):
        candidate = review(
            reviewer_system=" chatgpt ",
            reviewer_model="  gpt-5.6   sol ",
        )
        result = review_readiness.evaluate(
            pr(different_required="yes"),
            [candidate],
        )
        self.assertFalse(result.ready)
        self.assertIn("different reviewer", result.reason.lower())

    def test_same_system_unknown_model_does_not_satisfy_different_reviewer_gate(self):
        candidate = review(
            reviewer_system="ChatGPT",
            reviewer_model="unknown",
        )
        result = review_readiness.evaluate(
            pr(different_required="yes"),
            [candidate],
        )
        self.assertFalse(result.ready)
        self.assertIn("different reviewer", result.reason.lower())

    def test_known_different_system_can_qualify_with_unknown_model(self):
        candidate = review(
            reviewer_system="Human",
            reviewer_model="unknown",
        )
        result = review_readiness.evaluate(
            pr(different_required="yes"),
            [candidate],
        )
        self.assertTrue(result.ready)

    def test_different_reviewer_gate_accepts_different_signature(self):
        candidate = review(
            reviewer_system="Claude Code",
            reviewer_model="Sonnet",
        )
        result = review_readiness.evaluate(
            pr(different_required="yes"),
            [candidate],
        )
        self.assertTrue(result.ready)
        self.assertEqual(result.matched_review_id, 101)

    def test_stale_reviewed_commit_fails(self):
        result = review_readiness.evaluate(
            pr(), [review(reviewed_commit=OTHER, commit_id=OTHER)]
        )
        self.assertFalse(result.ready)
        self.assertIn("current head", result.reason)

    def test_declared_blocking_findings_fail(self):
        result = review_readiness.evaluate(pr(), [review(blocking="R1")])
        self.assertFalse(result.ready)
        self.assertIn("blocking", result.reason.lower())

    def test_missing_or_malformed_review_gate_fails_closed(self):
        bodies = [
            "## Review target\n- Different reviewer required: no",
            "## Review target\n- Formal review required: maybe\n- Different reviewer required: no",
            "## Review target\n- Formal review required: yes",
            "## Review target\n- Formal review required: yes\n- Different reviewer required: maybe",
        ]
        for body in bodies:
            with self.subTest(body=body):
                result = review_readiness.evaluate(pr(body=body), [])
                self.assertFalse(result.ready)
                self.assertIn("review", result.reason.lower())

    def test_inconsistent_no_formal_but_different_required_fails_closed(self):
        result = review_readiness.evaluate(
            pr(formal_required="no", different_required="yes"),
            [],
        )
        self.assertFalse(result.ready)
        self.assertIn("inconsistent", result.reason.lower())

    def test_no_formal_review_required_passes_without_review(self):
        result = review_readiness.evaluate(
            pr(formal_required="no", different_required="no"),
            [],
        )
        self.assertTrue(result.ready)
        self.assertIsNone(result.matched_review_id)

    def test_api_commit_id_mismatch_fails(self):
        result = review_readiness.evaluate(pr(), [review(commit_id=OTHER)])
        self.assertFalse(result.ready)
        self.assertIn("current head", result.reason)

    def test_malformed_review_provenance_does_not_satisfy_readiness(self):
        malformed = {
            "id": 102,
            "state": "COMMENTED",
            "commit_id": HEAD,
            "body": "## Review Result\n- Blocking findings: none\n",
        }
        result = review_readiness.evaluate(pr(), [malformed])
        self.assertFalse(result.ready)
        self.assertIn("formal review", result.reason.lower())

    def test_legacy_v1_provenance_does_not_satisfy_v2_readiness(self):
        candidate = review(version="1")
        result = review_readiness.evaluate(pr(), [candidate])
        self.assertFalse(result.ready)
        self.assertIn("version", result.reason.lower())

    def test_later_blocking_review_supersedes_earlier_clean_review(self):
        clean = review(review_id=101)
        blocking = review(review_id=102, blocking="R1")
        result = review_readiness.evaluate(pr(), [clean, blocking])
        self.assertFalse(result.ready)
        self.assertIn("blocking", result.reason.lower())

    def test_later_request_changes_supersedes_earlier_clean_review(self):
        clean = review(review_id=101)
        request_changes = review(
            review_id=102,
            state="CHANGES_REQUESTED",
            decision="REQUEST_CHANGES",
            blocking="R1",
        )
        result = review_readiness.evaluate(pr(), [clean, request_changes])
        self.assertFalse(result.ready)
        self.assertIn("blocking", result.reason.lower())

    def test_newer_malformed_request_changes_blocks_older_clean_review(self):
        clean = review(review_id=101)
        malformed_request_changes = {
            "id": 102,
            "state": "CHANGES_REQUESTED",
            "commit_id": HEAD,
            "body": "Requesting changes without managed provenance",
        }
        result = review_readiness.evaluate(
            pr(),
            [clean, malformed_request_changes],
        )
        self.assertFalse(result.ready)
        self.assertIn("request", result.reason.lower())

    def test_fresh_clean_review_supersedes_earlier_blocker(self):
        blocking = review(review_id=101, blocking="R1")
        clean = review(review_id=102)
        result = review_readiness.evaluate(pr(), [blocking, clean])
        self.assertTrue(result.ready)
        self.assertEqual(result.matched_review_id, 102)

    def test_different_reviewer_gate_requires_latest_different_signature_review_clean(self):
        different_blocking = review(
            review_id=101,
            reviewer_system="Claude Code",
            reviewer_model="Sonnet",
            blocking="R1",
        )
        self_clean = review(review_id=102)
        result = review_readiness.evaluate(
            pr(different_required="yes"),
            [different_blocking, self_clean],
        )
        self.assertFalse(result.ready)
        self.assertIn("blocking", result.reason.lower())

    def test_api_state_and_declared_decision_must_match(self):
        candidate = review(state="COMMENTED", decision="APPROVE")
        result = review_readiness.evaluate(pr(), [candidate])
        self.assertFalse(result.ready)
        self.assertIn("decision", result.reason.lower())


if __name__ == "__main__":
    unittest.main()


def codex_summary(*, head=HEAD, status="completed", unresolved=False,
                  has_findings=False, author_id=199175422,
                  login="chatgpt-codex-connector[bot]", user_type="Bot",
                  comment_id=801, updated_at="2026-11-18T01:00:00Z"):
    payload = {
        "code_review": {
            "commit_sha": head,
            "status": status,
            "has_any_findings": has_findings,
            "has_unresolved_findings": unresolved,
        },
        "security_review": {
            "commit_sha": None, "status": None,
            "has_any_findings": None, "has_unresolved_findings": None,
        },
    }
    return {
        "id": comment_id,
        "updated_at": updated_at,
        "user": {"id": author_id, "login": login, "type": user_type},
        "body": ("<!-- codex-pull-request-review-summary -->\n"
                 "<!-- codex-review-state:v1 "
                 + json.dumps(payload, separators=(",", ":")) + " -->\n"),
    }


class CodexReviewEvidenceTests(unittest.TestCase):
    # The verifier receives this set ONLY after authenticating real GitHub
    # editor history. Fixture JSON can never provide it to the CLI.
    def evaluate(self, *args, **kwargs):
        return review_readiness.evaluate(
            *args, verified_codex_ids={801, 802}, **kwargs
        )

    def test_current_head_codex_bot_independently_reviews_codex_implementation(self):
        case = pr(different_required="yes", implementer_system="Codex",
                  implementer_model="GPT-6")
        outcome = self.evaluate(case, [], [codex_summary()])
        self.assertTrue(outcome.ready, outcome.reason)
        self.assertEqual(outcome.matched_review_id, 801)

    def test_current_head_bot_is_additional_formal_review_path(self):
        self.assertTrue(self.evaluate(pr(), [], [codex_summary()]).ready)
        self.assertFalse(self.evaluate(pr(), []).ready)

    def test_stale_or_pending_bot_evidence_fails(self):
        for packet in [
            codex_summary(head=OTHER),
            codex_summary(status="pending"),
            codex_summary(unresolved=True, has_findings=True),
            codex_summary(has_findings=None),
        ]:
            with self.subTest(packet=packet):
                self.assertFalse(self.evaluate(
                    pr(different_required="yes"), [], [packet]
                ).ready)

    def test_forged_bot_comments_fail(self):
        for change in (
            {"author_id": 79015263},
            {"login": "kinoko34077"},
            {"user_type": "User"},
        ):
            packet = codex_summary(**change)
            with self.subTest(change=change):
                self.assertFalse(self.evaluate(pr(), [], [packet]).ready)
        packet = codex_summary()
        packet["body"] += packet["body"]
        self.assertFalse(self.evaluate(pr(), [], [packet]).ready)

    def test_malformed_and_summary_only_text_fails(self):
        packet = codex_summary()
        packet["body"] = "Codex Review: Didn't find any major issues."
        self.assertFalse(self.evaluate(pr(), [], [packet]).ready)
        packet["body"] = (
            "<!-- codex-pull-request-review-summary -->\n"
            "<!-- codex-review-state:v1 {invalid} -->"
        )
        self.assertFalse(self.evaluate(pr(), [], [packet]).ready)

    def test_newer_stale_summary_supersedes_older_clean(self):
        old = codex_summary()
        newer = codex_summary(head=OTHER, comment_id=802,
                              updated_at="2026-11-18T02:00:00Z")
        self.assertFalse(self.evaluate(pr(), [], [old, newer]).ready)

    def test_native_request_changes_cannot_be_overridden_by_bot(self):
        native = review(state="CHANGES_REQUESTED", decision="REQUEST_CHANGES")
        self.assertFalse(self.evaluate(
            pr(different_required="yes"), [native], [codex_summary()]
        ).ready)

    def test_native_comment_blocking_findings_not_overridden(self):
        blocking = review(blocking="P1: unresolved loss of data")
        self.assertFalse(self.evaluate(pr(), [blocking], [codex_summary()]).ready)
        # A later clean formal Review on the same head can supersede a
        # previously declared COMMENT finding, without dismissing unrelated
        # native REQUEST_CHANGES.
        clear = review(review_id=202)
        self.assertTrue(self.evaluate(
            pr(), [blocking, clear], [codex_summary()]
        ).ready)

    def test_invalid_later_formal_cannot_clear_existing_blocker(self):
        first = review(blocking="P1: unresolved", review_id=201)
        for second in (
            review(review_id=202, version="1"),
            review(review_id=202, commit_id=OTHER),
            review(review_id=202, state="DISMISSED"),
        ):
            with self.subTest(second=second):
                result = self.evaluate(
                    pr(), [first, second], [codex_summary()]
                )
                self.assertFalse(result.ready)

    def test_existing_native_formal_review_remains_supported(self):
        self.assertTrue(self.evaluate(
            pr(), [review()], [codex_summary(head=OTHER)]
        ).ready)

    def test_bot_cannot_review_its_own_changes_as_independent(self):
        case = pr(different_required="yes",
                  implementer_system="chatgpt-codex-connector",
                  implementer_model="unknown")
        self.assertFalse(self.evaluate(
            case, [], [codex_summary()]
        ).ready)

    def test_unverified_edited_source_cannot_pass_from_fixture_json(self):
        self.assertFalse(review_readiness.evaluate(
            pr(), [], [codex_summary()]
        ).ready)
        self.assertTrue(self.evaluate(pr(), [], [codex_summary()]).ready)

    def test_live_graphql_edit_history_accepts_only_bot_edits(self):
        comment = codex_summary()
        comment["node_id"] = "IC_authoritative"
        comment["user"]["node_id"] = "BOT_authoritative"

        def exercise(editor_id):
            def api(request, timeout=20):
                path = request.full_url
                if path.endswith("/pulls/42"):
                    payload = {"head": {"sha": HEAD}, "body": pr_body()}
                elif "pulls/42/reviews?" in path:
                    payload = []
                elif "issues/42/comments?" in path:
                    payload = [comment]
                elif path.endswith("/graphql"):
                    query = json.loads(request.data.decode("utf-8"))["query"]
                    self.assertEqual(query.count("editor { ... on Bot { id } }"), 2)
                    self.assertNotIn("editor { id }", query)
                    payload = {"data": {"node": {
                        "id": "IC_authoritative", "body": comment["body"],
                        "editor": {"id": editor_id},
                        "lastEditedAt": "2026-11-18T01:00:00Z",
                        "userContentEdits": {
                            "pageInfo": {"hasNextPage": False},
                            "nodes": [{"editor": {"id": editor_id}}],
                        },
                    }}}
                else:
                    raise AssertionError("Unexpected API: " + path)
                return io.BytesIO(json.dumps(payload).encode("utf-8"))

            with mock.patch.dict(review_readiness.os.environ,
                                 {"GH_TOKEN": "fixture", "GH_API_URL": "https://api.github.com"},
                                 clear=True):
                with mock.patch.object(review_readiness.urllib.request,
                                       "urlopen", side_effect=api):
                    return review_readiness._github_review_packet(
                        "kinoko34077/devflow", 42
                    )

        pr_source, review_source, comment_source, verified = exercise("BOT_authoritative")
        self.assertIn(801, verified)
        self.assertTrue(review_readiness.evaluate(
            pr_source, review_source, comment_source,
            verified_codex_ids=verified,
        ).ready)
        self.assertEqual(exercise("USER_wrong")[3], set())

    def test_existing_gh_cli_is_used_without_new_credentials(self):
        comment = codex_summary()
        comment["node_id"] = "IC_from_gh"
        comment["user"]["node_id"] = "BOT_from_gh"

        def gh_run(command, **kwargs):
            self.assertEqual(command[:2], ["gh", "api"])
            resource = command[2]
            if resource.endswith("/pulls/42"):
                packet = {"head": {"sha": HEAD}, "body": pr_body()}
            elif "pulls/42/reviews?" in resource:
                packet = []
            elif "issues/42/comments?" in resource:
                packet = [comment]
            elif resource == "graphql":
                self.assertEqual(command[3], "-f")
                self.assertEqual(command[4].count("editor { ... on Bot { id } }"), 2)
                self.assertEqual(command[5:7], ["-F", "id=IC_from_gh"])
                packet = {"data": {"node": {
                    "id": "IC_from_gh", "body": comment["body"],
                    "editor": {"id": "BOT_from_gh"},
                    "lastEditedAt": "2026-11-18T02:00:00Z",
                    "userContentEdits": {"pageInfo": {"hasNextPage": False},
                                         "nodes": [{"editor": {"id": "BOT_from_gh"}}]},
                }}}
            else:
                raise AssertionError("unexpected gh endpoint " + resource)
            return mock.Mock(stdout=json.dumps(packet), returncode=0)

        with mock.patch.dict(review_readiness.os.environ, {}, clear=True):
            with mock.patch.object(review_readiness.subprocess, "run",
                                   side_effect=gh_run) as runner:
                pr_data, review_data, comments, verified = (
                    review_readiness._github_review_packet("kinoko34077/devflow", 42)
                )
        self.assertEqual(runner.call_count, 4)
        self.assertIn(801, verified)
        self.assertTrue(review_readiness.evaluate(
            pr_data, review_data, comments, verified_codex_ids=verified
        ).ready)

    def test_live_read_uses_existing_auth_only_and_fails_closed(self):
        with mock.patch.dict(review_readiness.os.environ, {}, clear=True):
            with mock.patch.object(review_readiness.subprocess, "run",
                                   side_effect=FileNotFoundError("gh unavailable")):
                with self.assertRaises(FileNotFoundError):
                    review_readiness._github_review_packet("kinoko34077/devflow", 1057)
        with self.assertRaisesRegex(ValueError, "owner/name"):
            review_readiness._github_review_packet("https://bad", 1)
        with mock.patch.dict(review_readiness.os.environ,
                             {"GH_TOKEN": "fake", "GH_API_URL": "http://example.com"},
                             clear=True):
            with self.assertRaisesRegex(ValueError, "api.github.com"):
                review_readiness._github_review_packet("kinoko34077/devflow", 1)
