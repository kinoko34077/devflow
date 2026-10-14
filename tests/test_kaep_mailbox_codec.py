"""Pure KAEP v0.2 conformance tests; no GitHub writes or agent launches."""
from __future__ import annotations
import copy
import unittest
from tools.kaep_mailbox_codec import (
    CLAUDE_CODE_FOOTER, InvalidMessage, MARKER, decode_comment, encode_comment, fingerprint,
    read_mailbox, validate, verify_reply_chain,
)

TASK = "kinoko34077/devflow#503"

def envelope(**override):
    data = {
        "schema_version": "kaep.message.v0.2",
        "exchange_id": "ex_test001",
        "message_id": "msg_test001",
        "in_reply_to": None,
        "task_ref": TASK,
        "recipient": "claude-code",
        "kind": "REQUEST",
        "intent": "PING",
        "idempotency_key": "kaep.test.001",
        "scope": {"repository": "kinoko34077/devflow", "expected_head": None, "effect": "READ_ONLY"},
        "payload": {"text": "read-only test request"},
        "evidence_refs": ["https://github.com/kinoko34077/devflow/issues/503"],
    }
    data.update(override)
    return data

class KAEPMailboxContract(unittest.TestCase):
    def reject(self, **kw):
        with self.assertRaises(InvalidMessage):
            encode_comment(envelope(**kw))

    def test_roundtrip(self):
        d = envelope()
        self.assertEqual(decode_comment(encode_comment(d), task_ref=TASK), d)

    def test_unicode(self):
        d = envelope(payload={"text": "日本語の疎通だけ"})
        self.assertEqual(decode_comment(encode_comment(d))["payload"], d["payload"])

    def test_field_whitelist(self):
        self.reject(sender="Claude Code")
        d = envelope()
        del d["kind"]
        with self.assertRaises(InvalidMessage): validate(d)

    def test_bad_id(self):
        self.reject(exchange_id="ex.bad")
        self.reject(message_id="msg+bad")

    def test_task_binding(self):
        with self.assertRaisesRegex(InvalidMessage, "TASK_MISMATCH"):
            decode_comment(encode_comment(envelope()), task_ref="kinoko34077/devflow#504")
        self.reject(scope={"repository": "kinoko34077/other", "expected_head": None, "effect": "READ_ONLY"})

    def test_head_guard(self):
        self.reject(scope={"repository": "kinoko34077/devflow", "expected_head": "abcd", "effect": "READ_ONLY"})
        self.assertEqual(validate(envelope(scope={"repository": "kinoko34077/devflow", "expected_head": "a"*40, "effect": "WRITE_INTENT"}))["scope"]["effect"], "WRITE_INTENT")

    def test_no_readonly_implement(self):
        self.reject(intent="IMPLEMENT")
        self.reject(intent="REVISE")

    def test_reply_requires_parent(self):
        self.reject(kind="ACK")
        self.reject(kind="RESULT")
        self.reject(kind="ACK", in_reply_to="msg_test001")

    def test_known_parent(self):
        a = envelope()
        b = envelope(message_id="msg_ack002", idempotency_key="kaep.test.002", kind="ACK", recipient="chatgpt", in_reply_to="msg_test001")
        verify_reply_chain([a,b])

    def test_unknown_parent(self):
        b = envelope(message_id="msg_ack002", idempotency_key="kaep.test.002", kind="ACK", in_reply_to="msg_unknown")
        with self.assertRaisesRegex(InvalidMessage, "UNKNOWN_PARENT"): verify_reply_chain([b])

    def test_cross_exchange_parent(self):
        a = envelope()
        b = envelope(exchange_id="ex_wrong001", message_id="msg_ack002", idempotency_key="kaep.test.002", kind="ACK", in_reply_to="msg_test001")
        with self.assertRaisesRegex(InvalidMessage, "CROSS_EXCHANGE_REPLY"): verify_reply_chain([a,b])

    def test_no_comment_prefix_or_suffix(self):
        body = encode_comment(envelope())
        with self.assertRaises(InvalidMessage): decode_comment("extra\n" + body)
        with self.assertRaises(InvalidMessage): decode_comment(body + "\nextra")

    def test_known_claude_code_footer_is_untrusted_decoration(self):
        d = envelope()
        body = encode_comment(d)
        self.assertEqual(decode_comment(body + CLAUDE_CODE_FOOTER, task_ref=TASK), d)
        self.assertEqual(fingerprint(decode_comment(body + CLAUDE_CODE_FOOTER)), fingerprint(d))

    def test_footer_variants_rejected(self):
        body = encode_comment(envelope())
        bad = [
            body + CLAUDE_CODE_FOOTER + CLAUDE_CODE_FOOTER,
            body + CLAUDE_CODE_FOOTER + "\n",
            body + CLAUDE_CODE_FOOTER + " ",
            body + CLAUDE_CODE_FOOTER.replace("Claude Code", "Claude Codex"),
            body + CLAUDE_CODE_FOOTER.replace("https://claude.ai/code", "https://example.invalid/"),
            body + CLAUDE_CODE_FOOTER.replace("\n\n---", "\n---"),
            body + "\n" + CLAUDE_CODE_FOOTER,
            body + "extra" + CLAUDE_CODE_FOOTER,
            CLAUDE_CODE_FOOTER,
            "extra\n" + body + CLAUDE_CODE_FOOTER,
        ]
        for b in bad:
            with self.subTest(b=b[-60:]), self.assertRaises(InvalidMessage):
                decode_comment(b)

    def test_footer_counts_toward_size_limit(self):
        body = encode_comment(envelope(payload={"text": "x" * 4000}))
        pad = 8192 - len((body + CLAUDE_CODE_FOOTER).encode())
        self.assertGreaterEqual(pad, 0)
        # exactly at the limit incl. footer is accepted (footer bytes are counted, not exempt)
        self.assertEqual(decode_comment(body + CLAUDE_CODE_FOOTER)["payload"]["text"], "x" * 4000)
        with self.assertRaisesRegex(InvalidMessage, "COMMENT_TOO_LARGE"):
            decode_comment(body + "y" * (pad + 1) + CLAUDE_CODE_FOOTER)

    def test_mailbox_with_decorated_ack(self):
        ping = envelope(message_id="msg_ping001", exchange_id="ex_ping001", idempotency_key="kaep.test.ping")
        ack = envelope(message_id="msg_ack001", exchange_id="ex_ping001", idempotency_key="kaep.test.ack",
                       in_reply_to="msg_ping001", recipient="chatgpt", kind="ACK")
        comments = [
            {"id": 11, "body": encode_comment(ping)},
            {"id": 12, "body": encode_comment(ack) + CLAUDE_CODE_FOOTER},
        ]
        got = read_mailbox(comments, task_ref=TASK)
        self.assertEqual([i for i, _ in got], [11, 12])
        self.assertEqual(got[1][1]["kind"], "ACK")

    def test_encoder_never_emits_footer(self):
        self.assertFalse(encode_comment(envelope()).endswith(CLAUDE_CODE_FOOTER))

    def test_duplicate_json_keys(self):
        body = encode_comment(envelope())
        body = body.replace('"kind": "REQUEST",', '"kind": "REQUEST",\n  "kind": "ACK",')
        with self.assertRaisesRegex(InvalidMessage, "DUPLICATE_JSON_KEY"): decode_comment(body)

    def test_utf8_size_and_text_length(self):
        self.reject(payload={"text": "a" * 4001})
        self.reject(payload={"text": "あ" * 4000})

    def test_control_character(self):
        self.reject(payload={"text": "secret\x00bad"})

    def test_evidence_url_whitelist(self):
        self.reject(evidence_refs=["https://example.com/secret"])
        self.reject(evidence_refs=["https://github.com/kinoko34077/devflow/issues/503"]*2)

    def test_idempotency_replay(self):
        d = envelope()
        comments = [{"id":10, "body":encode_comment(d)},{"id":11, "body":encode_comment(d)}]
        self.assertEqual(len(read_mailbox(comments, task_ref=TASK)),1)

    def test_idempotency_conflict(self):
        a = envelope()
        b = envelope(message_id="msg_other002")
        with self.assertRaisesRegex(InvalidMessage, "IDEMPOTENCY_CONFLICT"):
            read_mailbox([{"id":10,"body":encode_comment(a)},{"id":11,"body":encode_comment(b)}], task_ref=TASK)

    def test_message_id_collision(self):
        a = envelope()
        b = envelope(idempotency_key="kaep.test.002", payload={"text":"different"})
        with self.assertRaisesRegex(InvalidMessage, "MESSAGE_ID_COLLISION"):
            read_mailbox([{"id":10,"body":encode_comment(a)},{"id":11,"body":encode_comment(b)}], task_ref=TASK)

    def test_cursor_and_recipient(self):
        d = envelope()
        comments=[{"id":20,"body":"normal issue discussion"},{"id":21,"body":encode_comment(d)}]
        self.assertEqual(len(read_mailbox(comments,task_ref=TASK,after_id=20,recipient="claude-code")),1)
        self.assertEqual(read_mailbox(comments,task_ref=TASK,after_id=21),[])
        self.assertEqual(read_mailbox(comments,task_ref=TASK,recipient="chatgpt"),[])

    def test_invalid_comment_id(self):
        with self.assertRaises(InvalidMessage):
            read_mailbox([{"id":True,"body":encode_comment(envelope())}],task_ref=TASK)

    def test_fingerprint_stable(self):
        d=envelope()
        reversed_keys={k:d[k] for k in reversed(list(d))}
        self.assertEqual(fingerprint(d),fingerprint(reversed_keys))

if __name__ == "__main__":
    unittest.main()
