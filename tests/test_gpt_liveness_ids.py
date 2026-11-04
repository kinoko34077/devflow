from __future__ import annotations

from unittest.mock import patch
import unittest

from tools import gpt_liveness_ids


class GptLivenessIdTests(unittest.TestCase):
    def test_shared_generators_preserve_prefix_and_entropy_contract(self) -> None:
        with patch.object(gpt_liveness_ids.secrets, "token_hex", return_value="a" * 32):
            self.assertEqual(gpt_liveness_ids.new_chat_id(), "chat_" + "a" * 32)
            self.assertEqual(gpt_liveness_ids.new_session_id(), "session_" + "a" * 32)
            self.assertEqual(gpt_liveness_ids.new_turn_id(), "turn_" + "a" * 32)

    def test_generators_use_the_requested_entropy_size(self) -> None:
        with patch.object(gpt_liveness_ids.secrets, "token_hex", return_value="b" * 32) as token_hex:
            gpt_liveness_ids.new_chat_id()
            gpt_liveness_ids.new_session_id()
            gpt_liveness_ids.new_turn_id()

        self.assertEqual(token_hex.call_count, 3)
        token_hex.assert_called_with(16)


if __name__ == "__main__":
    unittest.main()

