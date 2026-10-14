"""KAEP request composer tests. Network POST never used; send behavior mocked."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.kaep_mailbox_codec import encode_comment, fingerprint, InvalidMessage
from tools.kaep_request_sender import make_request, send_request, main

REPO = "kinoko34077/devflow"
KEY = "kaep.request.sample0001"
TASK = REPO + "#503"
HEAD = "a" * 40
OTHER_HEAD = "b" * 40


def pages(*groups):
    return json.dumps(list(groups), ensure_ascii=False)


def comment(cid, msg, actor="kinoko34077"):
    return {"id": cid, "body": encode_comment(msg), "user": {"login": actor}}


def prepare(text=None, **kw):
    return make_request(
        pages([]) if text is None else text, repository=REPO, issue=503,
        recipient="claude-code", intent="ANALYZE", request_key=KEY,
        request_text="safe analysis only", expect_existing_actor="kinoko34077", **kw,
    )


class RequestSenderTests(unittest.TestCase):
    def test_valid_request_shape(self):
        message, existing = prepare()
        self.assertIsNone(existing)
        self.assertEqual(message["kind"], "REQUEST")
        self.assertIsNone(message["in_reply_to"])
        self.assertEqual(message["scope"]["effect"], "READ_ONLY")
        self.assertEqual(message["task_ref"], TASK)
        self.assertIsNone(message["scope"]["expected_head"])

    def test_exact_head_is_preserved_in_request(self):
        message, existing = prepare(expected_head=HEAD)
        self.assertIsNone(existing)
        self.assertEqual(message["scope"]["expected_head"], HEAD)
        self.assertEqual(message["scope"]["effect"], "READ_ONLY")
        self.assertEqual(message["task_ref"], TASK)

    def test_expected_head_is_strictly_validated(self):
        invalid = ["", "a" * 39, "a" * 41, "A" * 40,
                   "g" * 40, "a" * 39 + " ", True, 123]
        for head in invalid:
            with self.subTest(head=head):
                with self.assertRaisesRegex(InvalidMessage, "INVALID_EXPECTED_HEAD"):
                    prepare(expected_head=head)

    def test_same_head_request_reuses_existing_message(self):
        original, _ = prepare(expected_head=HEAD)
        duplicate, existing = prepare(
            pages([comment(11, original)]), expected_head=HEAD)
        self.assertEqual(original, duplicate)
        self.assertEqual(existing, 11)

    def test_changed_head_cannot_reuse_request_identity(self):
        original, _ = prepare(expected_head=HEAD)
        with self.assertRaisesRegex(InvalidMessage, "REQUEST_KEY_COLLISION"):
            prepare(pages([comment(11, original)]), expected_head=OTHER_HEAD)
        with self.assertRaisesRegex(InvalidMessage, "REQUEST_KEY_COLLISION"):
            prepare(pages([comment(11, original)]), expected_head=None)

    def test_head_is_in_dry_run_output_and_post_readback(self):
        with patch("tools.kaep_request_sender.post_comment") as post:
            prepared = send_request(
                repository=REPO, issue=503, recipient="claude-code",
                intent="ANALYZE", request_key=KEY, request_text="review",
                expect_existing_actor="kinoko34077",
                expected_head=HEAD, offline_pages=pages([]))
        self.assertEqual(prepared["expected_head"], HEAD)
        post.assert_not_called()
        message, _ = prepare(expected_head=HEAD)
        with patch("tools.kaep_request_sender.fetch_gh_pages",
                   side_effect=[pages([]), pages([comment(99, message)])]):
            with patch("tools.kaep_request_sender.post_comment",
                       return_value=99):
                result = send_request(
                    repository=REPO, issue=503, recipient="claude-code",
                    intent="ANALYZE", request_key=KEY, request_text="safe analysis only",
                    expect_existing_actor="kinoko34077", expected_head=HEAD,
                    do_send=True)
        self.assertEqual(result["status"], "SENT_AND_READ_BACK")
        self.assertEqual(result["expected_head"], HEAD)

    def test_cli_exact_head_offline_and_malformed_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "pages.json"
            t = Path(td) / "text.txt"
            p.write_text(pages([]), encoding="utf-8")
            t.write_text("read-only audit", encoding="utf-8")
            args = [
                "--repository", REPO, "--issue", "503",
                "--recipient", "claude-code", "--intent", "ANALYZE",
                "--request-key", KEY, "--text-file", str(t),
                "--expect-existing-actor", "kinoko34077",
                "--offline-pages", str(p),
            ]
            with patch("builtins.print") as out:
                code = main(args + ["--expected-head", HEAD])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.call_args.args[0])["expected_head"], HEAD)
            with patch("builtins.print") as out:
                code = main(args + ["--expected-head", "wrong"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out.call_args.args[0])["reason_code"],
                             "INVALID_EXPECTED_HEAD")

    def test_stable_idempotency(self):
        a, _=prepare()
        b, _=prepare()
        self.assertEqual(fingerprint(a), fingerprint(b))
        self.assertEqual(a["message_id"], b["message_id"])

    def test_key_changes_id(self):
        a, _=prepare()
        b, _=make_request(
            pages([]),repository=REPO,issue=503,recipient="claude-code",
            intent="ANALYZE",request_key="kaep.request.sample0002",
            request_text="safe analysis only",expect_existing_actor="kinoko34077"
        )
        self.assertNotEqual(a["message_id"],b["message_id"])

    def test_duplicate_request_is_not_reposted(self):
        a,_=prepare()
        inp=pages([comment(11,a)])
        with patch("tools.kaep_request_sender.post_comment") as post:
            result=send_request(
                repository=REPO,issue=503,recipient="claude-code",intent="ANALYZE",
                request_key=KEY,request_text="safe analysis only",
                expect_existing_actor="kinoko34077",offline_pages=inp
            )
        self.assertEqual(result["status"],"ALREADY_SENT")
        self.assertEqual(result["posted_comment_id"],11)
        post.assert_not_called()

    def test_key_collision_different_payload_rejected(self):
        a,_=prepare()
        with self.assertRaisesRegex(InvalidMessage,"REQUEST_KEY_COLLISION"):
            make_request(
                pages([comment(11,a)]),repository=REPO,issue=503,recipient="claude-code",
                intent="ANALYZE",request_key=KEY,request_text="changed content",
                expect_existing_actor="kinoko34077"
            )

    def test_existing_wrong_actor_not_trusted(self):
        a,_=prepare()
        with self.assertRaisesRegex(InvalidMessage,"EXISTING_ACTOR_MISMATCH"):
            prepare(pages([comment(11,a,actor="other")]))

    def test_unrelated_comments_ignored(self):
        a,_=prepare()
        b,existing=prepare(pages([{"id":9,"body":"ordinary discussion",
                                   "user":{"login":"kinoko34077"}}]))
        self.assertEqual(a,b)
        self.assertIsNone(existing)

    def test_bad_key_codec_rejects(self):
        with self.assertRaisesRegex(InvalidMessage,"INVALID_IDEMPOTENCY"):
            make_request(
                pages([]),repository=REPO,issue=503,recipient="claude-code",
                intent="PING",request_key="no",request_text="test",
                expect_existing_actor="kinoko34077"
            )

    def test_bad_target_rejected(self):
        with self.assertRaisesRegex(InvalidMessage,"INVALID_TARGET"):
            make_request(
                pages([]),repository="owner/bad",issue=503,recipient="claude-code",
                intent="PING",request_key=KEY,request_text="test",
                expect_existing_actor="kinoko34077"
            )

    def test_bad_intent(self):
        with self.assertRaisesRegex(InvalidMessage,"UNSUPPORTED_REQUEST"):
            make_request(
                pages([]),repository=REPO,issue=503,recipient="claude-code",
                intent="IMPLEMENT",request_key=KEY,request_text="write",
                expect_existing_actor="kinoko34077"
            )

    def test_empty_text(self):
        with self.assertRaisesRegex(InvalidMessage,"INVALID_REQUEST_TEXT"):
            make_request(
                pages([]),repository=REPO,issue=503,recipient="claude-code",
                intent="PING",request_key=KEY,request_text="",
                expect_existing_actor="kinoko34077"
            )

    def test_text_exceeds_limit(self):
        with self.assertRaises(InvalidMessage):
            make_request(
                pages([]),repository=REPO,issue=503,recipient="claude-code",
                intent="PING",request_key=KEY,request_text="あ"*4000,
                expect_existing_actor="kinoko34077"
            )

    def test_dry_run_has_no_network(self):
        with patch("tools.kaep_request_sender.post_comment") as post:
            result=send_request(
                repository=REPO,issue=503,recipient="claude-code",intent="PING",
                request_key=KEY,request_text="non-secret test",
                expect_existing_actor="kinoko34077",offline_pages=pages([])
            )
        self.assertEqual(result["status"],"PREPARED")
        self.assertFalse(result["agent_woken"])
        post.assert_not_called()

    def test_offline_cannot_send(self):
        with self.assertRaisesRegex(InvalidMessage,"OFFLINE_POST_FORBIDDEN"):
            send_request(
                repository=REPO,issue=503,recipient="claude-code",intent="PING",
                request_key=KEY,request_text="non-secret test",
                expect_existing_actor="kinoko34077",offline_pages=pages([]),
                do_send=True
            )

    def test_successful_post_verified(self):
        original=pages([])
        msg,_=prepare()
        after=pages([comment(99,msg)])
        with patch("tools.kaep_request_sender.fetch_gh_pages",side_effect=[original,after]):
            with patch("tools.kaep_request_sender.post_comment",return_value=99) as post:
                result=send_request(
                    repository=REPO,issue=503,recipient="claude-code",
                    intent="ANALYZE",request_key=KEY,
                    request_text="safe analysis only",
                    expect_existing_actor="kinoko34077",do_send=True
                )
        post.assert_called_once()
        self.assertEqual(result["status"],"SENT_AND_READ_BACK")
        self.assertEqual(result["posted_comment_id"],99)

    def test_request_post_readback_wrong_actor_is_rejected(self):
        src = pages([])
        msg, _ = prepare()
        after = pages([comment(99, msg, actor="unrelated-user")])
        with patch("tools.kaep_request_sender.fetch_gh_pages",
                   side_effect=[src, after]):
            with patch("tools.kaep_request_sender.post_comment",
                       return_value=99):
                with self.assertRaisesRegex(InvalidMessage, "READBACK_ACTOR_MISMATCH"):
                    send_request(
                        repository=REPO, issue=503, recipient="claude-code",
                        intent="ANALYZE", request_key=KEY,
                        request_text="safe analysis only",
                        expect_existing_actor="kinoko34077",
                        do_send=True,
                    )

    def test_post_readback_failure(self):
        with patch("tools.kaep_request_sender.fetch_gh_pages",side_effect=[pages([]),pages([])]):
            with patch("tools.kaep_request_sender.post_comment",return_value=99):
                with self.assertRaisesRegex(InvalidMessage,"READBACK_UNCONFIRMED"):
                    send_request(
                        repository=REPO,issue=503,recipient="claude-code",
                        intent="ANALYZE",request_key=KEY,
                        request_text="safe analysis only",
                        expect_existing_actor="kinoko34077",do_send=True
                    )

    def test_cli_offline_preparation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"pages.json"
            t=Path(td)/"text.txt"
            p.write_text(pages([]),encoding="utf-8")
            t.write_text("non-secret task",encoding="utf-8")
            with patch("builtins.print") as out, patch("tools.kaep_request_sender.post_comment") as post:
                code=main([
                    "--repository",REPO,"--issue","503",
                    "--recipient","claude-code","--intent","ANALYZE",
                    "--request-key",KEY,"--text-file",str(t),
                    "--expect-existing-actor","kinoko34077",
                    "--offline-pages",str(p)
                ])
            self.assertEqual(code,0)
            post.assert_not_called()
            self.assertEqual(json.loads(out.call_args.args[0])["status"],"PREPARED")

    def test_cli_offline_write_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"pages.json"
            t=Path(td)/"text.txt"
            p.write_text(pages([]),encoding="utf-8")
            t.write_text("non-secret task",encoding="utf-8")
            with patch("builtins.print") as out:
                code=main([
                    "--repository",REPO,"--issue","503",
                    "--recipient","claude-code","--intent","ANALYZE",
                    "--request-key",KEY,"--text-file",str(t),
                    "--expect-existing-actor","kinoko34077",
                    "--offline-pages",str(p),"--send"
                ])
            self.assertEqual(code,2)
            self.assertIn("OFFLINE_POST_FORBIDDEN",out.call_args.args[0])


if __name__=="__main__":
    unittest.main()
