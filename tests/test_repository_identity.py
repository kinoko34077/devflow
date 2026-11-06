import unittest

from tools.repository_identity import is_repository_name


class RepositoryIdentityTests(unittest.TestCase):
    def test_accepts_github_style_names_and_outer_whitespace(self):
        self.assertTrue(is_repository_name("kinoko34077/devflow"))
        self.assertTrue(is_repository_name("  owner/repository  "))

    def test_rejects_non_string_or_malformed_names(self):
        for value in (None, "", "owner", "/repository", "owner/", "owner/repo/name"):
            with self.subTest(value=value):
                self.assertFalse(is_repository_name(value))
