"""KAEP M1 reply preflight/explicit-send tests; network is mocked."""
from __future__ import annotations

import ast
import json
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import kaep_reply_sender
from tools.kaep_mailbox_codec import InvalidMessage, encode_comment, fingerprint, read_mailbox
from tools.kaep_reply_sender import (
    FIXED_ACK, make_reply, post_comment, send_reply, main,
)

REPO = "kinoko34077/devflow"
TASK = REPO + "#503"
PARENT = "msg_claudem1ping20261013"


def parent(*, effect="READ_ONLY", intent="PING", kind="REQUEST",
           message_id=PARENT, recipient="claude-code"):
    return {
        "schema_version": "kaep.message.v0.2",
        "exchange_id": "ex_claudeecho20261013",
        "message_id": message_id,
        "in_reply_to": None,
        "task_ref": TASK,
        "recipient": recipient,
        "kind": kind,
        "intent": intent,
        "idempotency_key": "kaep.test.parent." + message_id,
        "scope": {"repository": REPO, "expected_head": None, "effect": effect},
        "payload": {"text": "Read-only ping"},
        "evidence_refs": [],
    }


def comment(cid, message, actor="kinoko34077"):
    return {"id": cid, "body": encode_comment(message), "user": {"login": actor, "id": 79015263 if actor == "kinoko34077" else 999999999}}


def pages(*pages_):
    return json.dumps(list(pages_), ensure_ascii=False)


def build(source=None, **kwargs):
    return make_reply(
        source or pages([comment(11, parent())]),
        repository=REPO, issue=503, parent_message_id=PARENT, kind="ACK",
        response_text=FIXED_ACK, expect_actor="kinoko34077", **kwargs,
    )


class ReplyContractTests(unittest.TestCase):
    def test_reply_roles_use_codec_recipient_set(self):
        source = Path(kaep_reply_sender.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(kaep_reply_sender.__file__))
        codec_imports = {
            alias.name
            for node in tree.body
            if (isinstance(node, ast.ImportFrom)
                    and node.module == "tools.kaep_mailbox_codec")
            for alias in node.names
        }
        self.assertIn("RECIPIENTS", codec_imports)

    def test_sender_preflight_decodes_each_issue_mailbox_once(self):
        source = pages([comment(11, parent())])
        with patch("tools.kaep_mailbox_support.read_mailbox",
                   wraps=read_mailbox) as read:
            reply, existing = build(source)
        self.assertIsNone(existing)
        self.assertEqual(reply["in_reply_to"], PARENT)
        # Prior implementation decoded the entire Issue twice to reserve
        # quarantined IDs/keys after finding an eligible parent.
        self.assertEqual(read.call_count, 1)

    def test_unrelated_cross_exchange_is_not_a_global_reply_blocker(self):
        good = parent()
        bad = parent(message_id="msg_bad_root003")
        bad["exchange_id"] = "ex_bad003"
        bad["in_reply_to"] = PARENT
        source = pages([comment(11, good), comment(12, bad)])
        response, existing = build(source)
        self.assertIsNone(existing)
        self.assertEqual(response["in_reply_to"], PARENT)
        with self.assertRaisesRegex(InvalidMessage, "PARENT_NOT_FOUND"):
            make_reply(
                source, repository=REPO, issue=503,
                parent_message_id="msg_bad_root003", kind="ACK",
                response_text=FIXED_ACK, expect_actor="kinoko34077",
            )

    def test_quarantined_reply_id_or_key_still_reserves_identity(self):
        good = parent()
        expected_reply, _ = build()
        for mode in ("message_id", "idempotency_key"):
            with self.subTest(mode=mode):
                invalid = dict(expected_reply)
                invalid["exchange_id"] = "ex_wrong003"
                if mode == "message_id":
                    invalid["idempotency_key"] = "kaep.wrong.003"
                else:
                    invalid["message_id"] = "msg_wrong003"
                # The foreign parent remains known: this is a quarantinable
                # cross-exchange link, not a truncated/unknown-parent mailbox.
                source = pages([comment(11, good), comment(12, invalid)])
                with self.assertRaisesRegex(InvalidMessage, "REPLY_COLLISION"):
                    build(source)

    def test_ack_shape(self):
        reply, existing = build()
        self.assertIsNone(existing)
        self.assertEqual(reply["in_reply_to"], PARENT)
        self.assertEqual(reply["kind"], "ACK")
        self.assertEqual(reply["recipient"], "chatgpt")
        self.assertEqual(reply["scope"]["effect"], "READ_ONLY")
        self.assertEqual(reply["exchange_id"], "ex_claudeecho20261013")

    def test_answer_deterministic(self):
        source = pages([comment(11, parent())])
        a, _ = make_reply(source, repository=REPO, issue=503,
                          parent_message_id=PARENT, kind="ANSWER",
                          response_text="Hello from a genuine future worker",
                          expect_actor="kinoko34077")
        b, _ = make_reply(source, repository=REPO, issue=503,
                          parent_message_id=PARENT, kind="ANSWER",
                          response_text="Hello from a genuine future worker",
                          expect_actor="kinoko34077")
        self.assertEqual(fingerprint(a), fingerprint(b))
        self.assertEqual(a["payload"]["text"], "Hello from a genuine future worker")

    def test_different_kinds_get_distinct_ids(self):
        src = pages([comment(11, parent())])
        a, _ = make_reply(src, repository=REPO, issue=503,
                          parent_message_id=PARENT, kind="ACK",
                          response_text=FIXED_ACK, expect_actor="kinoko34077")
        b, _ = make_reply(src, repository=REPO, issue=503,
                          parent_message_id=PARENT, kind="ANSWER",
                          response_text="status ok", expect_actor="kinoko34077")
        self.assertNotEqual(a["message_id"], b["message_id"])

    def test_existing_reply_prevents_duplicate_post(self):
        src = pages([comment(11, parent())])
        a, _ = make_reply(src, repository=REPO, issue=503,
                          parent_message_id=PARENT, kind="ACK",
                          response_text=FIXED_ACK, expect_actor="kinoko34077")
        src_with_reply = pages([comment(11, parent()), comment(12, a)])
        with patch("tools.kaep_reply_sender.post_comment") as post:
            result = send_reply(repository=REPO, issue=503,
                                parent_message_id=PARENT, kind="ACK",
                                response_text=FIXED_ACK, expect_actor="kinoko34077",
                                offline_pages=src_with_reply)
        post.assert_not_called()
        self.assertEqual(result["status"], "ALREADY_SENT")
        self.assertEqual(result["posted_comment_id"], 12)

    def test_reply_text_collision_rejected(self):
        original, _ = build()
        src = pages([comment(11, parent()), comment(12, original)])
        with self.assertRaisesRegex(InvalidMessage, "REPLY_COLLISION"):
            make_reply(src, repository=REPO, issue=503,
                       parent_message_id=PARENT, kind="ACK",
                       response_text="not the fixed original",
                       expect_actor="kinoko34077")

    def test_bad_parent_actor(self):
        src = pages([comment(11, parent(), actor="random-attacker")])
        with self.assertRaisesRegex(InvalidMessage, "PARENT_ACTOR_MISMATCH"):
            build(src)

    def test_malformed_parent(self):
        with self.assertRaisesRegex(InvalidMessage, "PARENT_NOT_FOUND"):
            build(pages([{"id": 11, "body": "ordinary", "user": {"login":"kinoko34077", "id":79015263}}]))

    def test_wrong_target_recipient(self):
        src = pages([comment(11, parent(recipient="codex"))])
        with self.assertRaisesRegex(InvalidMessage, "INVALID_PARENT_INTENT"):
            build(src)

    def test_write_intent_is_rejected(self):
        src = pages([comment(11, parent(effect="WRITE_INTENT"))])
        with self.assertRaisesRegex(InvalidMessage, "UNSUPPORTED_EFFECT"):
            build(src)

    def test_implement_intent_is_rejected(self):
        src = pages([comment(11, parent(effect="WRITE_INTENT", intent="IMPLEMENT"))])
        with self.assertRaisesRegex(InvalidMessage, "UNSUPPORTED_EFFECT"):
            build(src)

    def test_ack_to_question_rejected(self):
        src = pages([comment(11, parent(kind="QUESTION"))])
        with self.assertRaisesRegex(InvalidMessage, "INVALID_REPLY_KIND"):
            build(src)

    def test_answer_to_question_allowed(self):
        src = pages([comment(11, parent(kind="QUESTION"))])
        reply, _ = make_reply(src, repository=REPO, issue=503,
                              parent_message_id=PARENT, kind="ANSWER",
                              response_text="reply", expect_actor="kinoko34077")
        self.assertEqual(reply["kind"], "ANSWER")

    def test_bad_reply_text(self):
        with self.assertRaisesRegex(InvalidMessage, "INVALID_REPLY_TEXT"):
            make_reply(pages([comment(11,parent())]),
                       repository=REPO, issue=503, parent_message_id=PARENT,
                       kind="ACK", response_text=" ", expect_actor="kinoko34077")

    def test_bad_kind(self):
        with self.assertRaisesRegex(InvalidMessage, "INVALID_REPLY_OPTIONS"):
            make_reply(pages([comment(11,parent())]),
                       repository=REPO, issue=503, parent_message_id=PARENT,
                       kind="RESULT", response_text="result", expect_actor="kinoko34077")

    def test_bad_actor(self):
        with self.assertRaisesRegex(InvalidMessage, "INVALID_REPLY_OPTIONS"):
            make_reply(pages([comment(11,parent())]),
                       repository=REPO, issue=503, parent_message_id=PARENT,
                       kind="ACK", response_text=FIXED_ACK, expect_actor="bad login")

    def test_gpt_targeted_request_can_reply_to_claude(self):
        src = pages([comment(11, parent(recipient="chatgpt"), actor="kinoko34077")])
        reply, previous = make_reply(
            src, repository=REPO, issue=503, parent_message_id=PARENT,
            kind="ANSWER", response_text="GPT response prepared",
            expect_actor="kinoko34077",
            parent_recipient="chatgpt", reply_recipient="claude-code",
        )
        self.assertIsNone(previous)
        self.assertEqual(reply["recipient"], "claude-code")
        self.assertEqual(reply["in_reply_to"], PARENT)
        self.assertEqual(reply["scope"]["effect"], "READ_ONLY")

    def test_codex_targeted_request_can_reply_to_gpt(self):
        src = pages([comment(11, parent(recipient="codex"))])
        reply, _ = make_reply(
            src, repository=REPO, issue=503, parent_message_id=PARENT,
            kind="ACK", response_text=FIXED_ACK, expect_actor="kinoko34077",
            parent_recipient="codex", reply_recipient="chatgpt",
        )
        self.assertEqual(reply["recipient"], "chatgpt")

    def test_route_must_not_reply_to_same_recipient(self):
        src = pages([comment(11, parent(recipient="chatgpt"))])
        with self.assertRaisesRegex(InvalidMessage, "INVALID_REPLY_ROUTE"):
            make_reply(
                src, repository=REPO, issue=503, parent_message_id=PARENT,
                kind="ANSWER", response_text="same agent",
                expect_actor="kinoko34077",
                parent_recipient="chatgpt", reply_recipient="chatgpt",
            )

    def test_expected_parent_recipient_must_match_message(self):
        src = pages([comment(11, parent(recipient="chatgpt"))])
        with self.assertRaisesRegex(InvalidMessage, "INVALID_PARENT_INTENT"):
            make_reply(
                src, repository=REPO, issue=503, parent_message_id=PARENT,
                kind="ANSWER", response_text="wrong route",
                expect_actor="kinoko34077",
                parent_recipient="claude-code", reply_recipient="chatgpt",
            )

    def test_reverse_route_send_readback(self):
        src = pages([comment(11, parent(recipient="chatgpt"))])
        reply, _ = make_reply(
            src, repository=REPO, issue=503, parent_message_id=PARENT,
            kind="ANSWER", response_text="verified via readback",
            expect_actor="kinoko34077", parent_recipient="chatgpt",
            reply_recipient="claude-code",
        )
        after = pages([comment(11, parent(recipient="chatgpt")), comment(12, reply)])
        with patch("tools.kaep_reply_sender.fetch_gh_pages", side_effect=[src, after]):
            with patch("tools.kaep_reply_sender.post_comment", return_value=12) as post:
                result = send_reply(
                    repository=REPO, issue=503, parent_message_id=PARENT,
                    kind="ANSWER", response_text="verified via readback",
                    expect_actor="kinoko34077", do_send=True,
                    parent_recipient="chatgpt", reply_recipient="claude-code",
                )
        post.assert_called_once()
        self.assertEqual(result["status"], "SENT_AND_READ_BACK")

    def test_cli_reverse_route_dry_run_does_not_post(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pages.json"
            t = Path(d) / "answer.txt"
            p.write_text(pages([comment(11, parent(recipient="chatgpt"))]),
                         encoding="utf-8")
            t.write_text("non-secret reply", encoding="utf-8")
            with patch("tools.kaep_reply_sender.subprocess.run") as network:
                with patch("builtins.print") as output:
                    exitcode = main([
                        "--repository", REPO, "--issue", "503",
                        "--parent-message-id", PARENT, "--kind", "ANSWER",
                        "--text-file", str(t), "--expect-actor", "kinoko34077",
                        "--parent-recipient", "chatgpt",
                        "--reply-recipient", "claude-code",
                        "--offline-pages", str(p),
                    ])
            self.assertEqual(exitcode, 0)
            network.assert_not_called()
            self.assertEqual(json.loads(output.call_args.args[0])["status"],
                             "PREPARED")

    def test_existing_reply_actor_mismatch_is_not_acknowledged(self):
        src = pages([comment(11, parent())])
        reply, _ = build(src)
        hostile = pages([comment(11, parent()),
                         comment(12, reply, actor="unrelated-user")])
        with self.assertRaisesRegex(InvalidMessage, "EXISTING_REPLY_ACTOR_MISMATCH"):
            make_reply(
                hostile, repository=REPO, issue=503,
                parent_message_id=PARENT, kind="ACK",
                response_text=FIXED_ACK, expect_actor="kinoko34077",
            )

    def test_post_readback_requires_expected_reply_actor(self):
        before = pages([comment(11, parent())])
        reply, _ = build(before)
        after = pages([comment(11, parent()),
                       comment(12, reply, actor="unrelated-user")])
        with patch("tools.kaep_reply_sender.fetch_gh_pages",
                   side_effect=[before, after]):
            with patch("tools.kaep_reply_sender.post_comment",
                       return_value=12):
                with self.assertRaisesRegex(InvalidMessage, "READBACK_ACTOR_MISMATCH"):
                    send_reply(
                        repository=REPO, issue=503, parent_message_id=PARENT,
                        kind="ACK", response_text=FIXED_ACK,
                        expect_actor="kinoko34077", do_send=True,
                    )

    def test_distinct_reply_actor_can_be_explicit(self):
        before = pages([comment(11, parent())])
        reply, _ = make_reply(
            before, repository=REPO, issue=503,
            parent_message_id=PARENT, kind="ACK",
            response_text=FIXED_ACK, expect_actor="kinoko34077",
            reply_actor="claude-transport",
        )
        after = pages([comment(11, parent()),
                       comment(12, reply, actor="claude-transport")])
        result = send_reply(
            repository=REPO, issue=503, parent_message_id=PARENT,
            kind="ACK", response_text=FIXED_ACK,
            expect_actor="kinoko34077", reply_actor="claude-transport",
            offline_pages=after,
        )
        self.assertEqual(result["status"], "ALREADY_SENT")

    def test_reply_cannot_be_offline_sent(self):
        with self.assertRaisesRegex(InvalidMessage, "OFFLINE_POST_FORBIDDEN"):
            send_reply(repository=REPO, issue=503, parent_message_id=PARENT,
                       kind="ACK", response_text=FIXED_ACK,
                       expect_actor="kinoko34077", do_send=True,
                       offline_pages=pages([comment(11,parent())]))

    def test_dry_run_does_not_post(self):
        with patch("tools.kaep_reply_sender.post_comment") as post:
            r = send_reply(repository=REPO, issue=503,
                           parent_message_id=PARENT, kind="ACK",
                           response_text=FIXED_ACK, expect_actor="kinoko34077",
                           offline_pages=pages([comment(11,parent())]))
        post.assert_not_called()
        self.assertEqual(r["status"], "PREPARED")

    def test_duplicate_protocol_conflict_blocks(self):
        p = parent()
        another = parent(message_id="msg_otherparent")
        another["idempotency_key"] = p["idempotency_key"]
        src = pages([comment(11,p),comment(12,another)])
        with self.assertRaisesRegex(InvalidMessage, "IDEMPOTENCY_CONFLICT"):
            build(src)

    @patch("tools.kaep_reply_sender.subprocess.run")
    def test_gh_post_uses_explicit_post_and_stdin(self, run):
        run.return_value = subprocess.CompletedProcess([],0,stdout='{"id":1234}',stderr="")
        self.assertEqual(post_comment(repository=REPO, issue=503,
                                      body="inert test"),1234)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:4], ["gh", "api", "-X", "POST"])
        self.assertIn("--input", argv)
        self.assertNotIn("inert test", argv)
        self.assertIn('"body": "inert test"',run.call_args.kwargs["input"])

    @patch("tools.kaep_reply_sender.subprocess.run")
    def test_gh_post_known_failure_has_redacted_code(self, run):
        run.return_value = subprocess.CompletedProcess([],1,stdout="DENIED",stderr="secret")
        with self.assertRaisesRegex(InvalidMessage, "POST_UNKNOWN_READ_BEFORE_RETRY"):
            post_comment(repository=REPO, issue=503, body="safe")

    @patch("tools.kaep_reply_sender.subprocess.run")
    def test_gh_post_timeout_has_ambiguous_code(self, run):
        run.side_effect = subprocess.TimeoutExpired(cmd="gh",timeout=30)
        with self.assertRaisesRegex(InvalidMessage, "POST_AMBIGUOUS_READ_BEFORE_RETRY"):
            post_comment(repository=REPO, issue=503,body="safe")

    def test_send_revalidates_readback(self):
        original=pages([comment(11,parent())])
        reply,_=build(original)
        after=pages([comment(11,parent()),comment(12,reply)])
        with patch("tools.kaep_reply_sender.fetch_gh_pages",side_effect=[original,after]):
            with patch("tools.kaep_reply_sender.post_comment",return_value=12) as post:
                result=send_reply(repository=REPO,issue=503,parent_message_id=PARENT,
                                  kind="ACK",response_text=FIXED_ACK,
                                  expect_actor="kinoko34077",do_send=True)
        self.assertEqual(result["status"],"SENT_AND_READ_BACK")
        post.assert_called_once()

    def test_bad_readback_is_blocked(self):
        src=pages([comment(11,parent())])
        with patch("tools.kaep_reply_sender.fetch_gh_pages",side_effect=[src,src]):
            with patch("tools.kaep_reply_sender.post_comment",return_value=12):
                with self.assertRaisesRegex(InvalidMessage,"READBACK_UNCONFIRMED"):
                    send_reply(repository=REPO,issue=503,parent_message_id=PARENT,
                               kind="ACK",response_text=FIXED_ACK,
                               expect_actor="kinoko34077",do_send=True)

    def test_cli_offline_ack_dry_run(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/"pages.json"
            file.write_text(pages([comment(11,parent())]),encoding="utf-8")
            with patch("builtins.print") as output:
                with patch("tools.kaep_reply_sender.subprocess.run") as net:
                    code=main(["--repository",REPO,"--issue","503",
                               "--parent-message-id",PARENT,"--kind","ACK",
                               "--expect-actor","kinoko34077",
                               "--offline-pages",str(file)])
            net.assert_not_called()
            self.assertEqual(code,0)
            self.assertEqual(json.loads(output.call_args.args[0])["status"],"PREPARED")

    def test_cli_blocked_offline_send(self):
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/"pages.json"
            file.write_text(pages([comment(11,parent())]),encoding="utf-8")
            with patch("builtins.print") as output:
                code=main(["--repository",REPO,"--issue","503",
                           "--parent-message-id",PARENT,"--kind","ACK",
                           "--expect-actor","kinoko34077",
                           "--offline-pages",str(file),"--send"])
            self.assertEqual(code,2)
            self.assertIn("OFFLINE_POST_FORBIDDEN",output.call_args.args[0])

    def test_cli_answer_needs_text(self):
        with patch("builtins.print") as output:
            code=main(["--repository",REPO,"--issue","503",
                       "--parent-message-id",PARENT,"--kind","ANSWER",
                       "--expect-actor","kinoko34077"])
        self.assertEqual(code,2)
        self.assertIn("REPLY_TEXT_REQUIRED",output.call_args.args[0])


class NumericOwnerTrustRegression(unittest.TestCase):
    def test_parent_owner_id_rejected_when_missing_malformed_or_mismatched(self):
        for identity in ({}, {"id": True}, {"id": 999999999}, {"id": "79015263"}, {"id": 79015263, "login": "spoof"}):
            with self.subTest(identity=identity):
                original = comment(11, parent())
                original["user"] = {"login": "kinoko34077", **identity}
                with self.assertRaisesRegex(InvalidMessage, "PARENT_ACTOR_MISMATCH"):
                    build(pages([original]))


class ReviewFeedbackCompatibilityTests(unittest.TestCase):
    """Regression for archive #32 PR #54/#57/#58 Claude review replies."""

    def review_root(self, *, head="a" * 40, effect="WRITE_INTENT",
                    intent="REVIEW", kind="REVIEW_REQUEST"):
        root = parent(kind=kind, intent=intent, effect=effect,
                      message_id="msg_review_root_20261104")
        root["scope"]["expected_head"] = head
        root["evidence_refs"] = [f"https://github.com/{REPO}/pull/54"]
        return root

    def reply(self, root, *, kind="REVIEW_FEEDBACK", response="Native review submitted"):
        return make_reply(
            pages([comment(11, root)]), repository=REPO, issue=503,
            parent_message_id=root["message_id"], kind=kind,
            response_text=response, expect_actor="kinoko34077",
        )

    def test_review_feedback_exact_parent_scope_and_determinism(self):
        root = self.review_root()
        response, existing = self.reply(root)
        self.assertIsNone(existing)
        self.assertEqual(response["kind"], "REVIEW_FEEDBACK")
        self.assertEqual(response["intent"], "REVIEW")
        self.assertEqual(response["scope"], root["scope"])
        self.assertEqual(response["task_ref"], root["task_ref"])
        self.assertEqual(response["exchange_id"], root["exchange_id"])
        self.assertEqual(response["in_reply_to"], root["message_id"])
        self.assertEqual(response["evidence_refs"], root["evidence_refs"])
        self.assertEqual(fingerprint(response), fingerprint(self.reply(root)[0]))

    def test_review_ack_and_blocked_are_valid_receipts(self):
        root = self.review_root()
        for kind in ("ACK", "BLOCKED"):
            with self.subTest(kind=kind):
                response, _ = self.reply(root, kind=kind)
                self.assertEqual(response["scope"]["effect"], "WRITE_INTENT")
                self.assertEqual(response["kind"], kind)

    def test_wrong_kind_and_scope_remain_rejected(self):
        root = self.review_root()
        with self.assertRaisesRegex(InvalidMessage, "INVALID_REPLY_KIND"):
            self.reply(root, kind="ANSWER")
        with self.assertRaisesRegex(InvalidMessage, "INVALID_REPLY_KIND"):
            self.reply(parent(), kind="REVIEW_FEEDBACK")
        for change in ({"intent": "REPORT"}, {"scope": {
            "repository": REPO, "expected_head": "a"*40, "effect": "READ_ONLY"
        }}, {"scope": {
            "repository": REPO, "expected_head": None, "effect": "WRITE_INTENT"
        }}):
            with self.subTest(change=change):
                invalid = self.review_root()
                invalid.update(change)
                with self.assertRaisesRegex(InvalidMessage, "UNSUPPORTED_REVIEW_PARENT"):
                    self.reply(invalid)

    def test_real_archive_review_request_shapes_without_private_payload(self):
        archive = "kinoko34077/github-history-archive"
        for pr, head in (
            (54, "83a06f2fa1a4575b6f395e54279ced61f32722e7"),
            (57, "311a92efdb83f51fb5cde75b8cc1a4ae9a90f460"),
            (58, "7e91345fe40dcee66f31afe48c90da8f8ce8f52b"),
        ):
            with self.subTest(pr=pr):
                root = self.review_root(head=head)
                root["message_id"] = f"msg_archive32_pr{pr}_fixture"
                root["task_ref"] = archive + "#32"
                root["scope"]["repository"] = archive
                root["evidence_refs"] = [f"https://github.com/{archive}/pull/{pr}"]
                result, existing = make_reply(
                    pages([comment(11, root)]), repository=archive, issue=32,
                    parent_message_id=root["message_id"],
                    kind="REVIEW_FEEDBACK",
                    response_text=f"PR #{pr} reviewed at {head}; see native review",
                    expect_actor="kinoko34077",
                )
                self.assertIsNone(existing)
                self.assertEqual(result["scope"]["expected_head"], head)
                self.assertEqual(result["scope"]["effect"], "WRITE_INTENT")

    def test_review_duplicate_and_changed_result_collision(self):
        root = self.review_root()
        initial = pages([comment(11, root)])
        response, _ = self.reply(root)
        history = pages([comment(11, root), comment(12, response)])
        with patch("tools.kaep_reply_sender.post_comment") as post:
            existing = send_reply(
                repository=REPO, issue=503,
                parent_message_id=root["message_id"],
                kind="REVIEW_FEEDBACK", response_text="Native review submitted",
                expect_actor="kinoko34077", offline_pages=history,
            )
        post.assert_not_called()
        self.assertEqual(existing["status"], "ALREADY_SENT")
        with self.assertRaisesRegex(InvalidMessage, "REPLY_COLLISION"):
            make_reply(history, repository=REPO, issue=503,
                       parent_message_id=root["message_id"], kind="REVIEW_FEEDBACK",
                       response_text="Different review result", expect_actor="kinoko34077")
        with patch("tools.kaep_reply_sender.fetch_gh_pages", side_effect=[initial, history]):
            with patch("tools.kaep_reply_sender.post_comment", return_value=12) as post:
                sent = send_reply(
                    repository=REPO, issue=503,
                    parent_message_id=root["message_id"], kind="REVIEW_FEEDBACK",
                    response_text="Native review submitted",
                    expect_actor="kinoko34077", do_send=True,
                )
        post.assert_called_once()
        self.assertEqual(sent["status"], "SENT_AND_READ_BACK")
        self.assertEqual(sent["posted_comment_id"], 12)

    def test_cli_review_dry_run_never_posts(self):
        root = self.review_root()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pages.json"
            txt = Path(d) / "review.txt"
            p.write_text(pages([comment(11, root)]), encoding="utf-8")
            txt.write_text("Claude review completed on exact head.", encoding="utf-8")
            with patch("builtins.print") as result:
                with patch("tools.kaep_reply_sender.subprocess.run") as net:
                    rc = main([
                        "--repository", REPO, "--issue", "503",
                        "--parent-message-id", root["message_id"],
                        "--kind", "REVIEW_FEEDBACK",
                        "--expect-actor", "kinoko34077",
                        "--text-file", str(txt), "--offline-pages", str(p),
                    ])
            self.assertEqual(rc, 0)
            net.assert_not_called()
            self.assertEqual(json.loads(result.call_args.args[0])["status"], "PREPARED")


if __name__=="__main__":
    unittest.main()

