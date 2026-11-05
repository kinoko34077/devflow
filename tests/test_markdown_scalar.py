import unittest

from tools.markdown_scalar import strip_scalar


class MarkdownScalarTests(unittest.TestCase):
    def test_trims_fenced_scalar(self):
        self.assertEqual(strip_scalar("  ```\nvalue\n```  "), "value")

    def test_trims_inline_scalar(self):
        self.assertEqual(strip_scalar(" `value` "), "value")


if __name__ == "__main__":
    unittest.main()
