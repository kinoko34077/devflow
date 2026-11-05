import unittest

from tools.markdown_sections import iter_h2_sections


class MarkdownSectionScannerTests(unittest.TestCase):
    def test_normalizes_line_endings_and_yields_h2_bodies(self):
        self.assertEqual(
            list(iter_h2_sections("## One\r\nvalue\r\n## Two\r\nnext")),
            [("One", "value"), ("Two", "next")],
        )

    def test_machine_block_begin_stops_previous_capture(self):
        body = "## Repository\nrepo\n<!-- DEVFLOW_META_BEGIN -->\nsecret\n## Next\nvalue"
        self.assertEqual(
            list(iter_h2_sections(body, reset_on_devflow_blocks=True)),
            [("Repository", "repo"), ("Next", "value")],
        )


if __name__ == "__main__":
    unittest.main()
