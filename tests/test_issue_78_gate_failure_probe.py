import unittest


class RequiredGateFailureProbe(unittest.TestCase):
    def test_expected_failure_probe(self):
        self.fail("temporary Issue #78 protection probe")
