import unittest

from tests.test_chat_worker_bootstrap import PortfolioV2ContractTests
from tools import chat_worker_bootstrap as cwb


class WorkClassDispositionRegressionTests(unittest.TestCase):
    def _portfolio_case(self):
        return PortfolioV2ContractTests()._portfolio_case()

    def test_out_of_class_human_gate_does_not_escalate_cycle(self):
        data = self._portfolio_case()
        data["request"]["accepted_work_classes"] = ["audit"]
        reviewer, implementer = data["evidence"]["frontier"]["candidates"]
        reviewer["human_gate"] = True
        implementer["work_class"] = "quickfix"

        result = cwb.classify(data["request"], data["evidence"])

        self.assertEqual("NO_ELIGIBLE_WORK", result["disposition"])
        self.assertEqual("ALL_CANDIDATES_OMITTED", result["reason_code"])

    def test_out_of_class_external_blocker_does_not_escalate_cycle(self):
        data = self._portfolio_case()
        data["request"]["accepted_work_classes"] = ["audit"]
        reviewer, implementer = data["evidence"]["frontier"]["candidates"]
        reviewer["external_blocker"] = True
        implementer["work_class"] = "quickfix"

        result = cwb.classify(data["request"], data["evidence"])

        self.assertEqual("NO_ELIGIBLE_WORK", result["disposition"])
        self.assertEqual("ALL_CANDIDATES_OMITTED", result["reason_code"])

    def test_in_class_human_gate_still_escalates_cycle(self):
        data = self._portfolio_case()
        data["request"]["accepted_work_classes"] = ["formal-review"]
        reviewer, implementer = data["evidence"]["frontier"]["candidates"]
        reviewer["human_gate"] = True
        implementer["work_class"] = "quickfix"

        result = cwb.classify(data["request"], data["evidence"])

        self.assertEqual("NEEDS_HUMAN", result["disposition"])
        self.assertEqual("HUMAN_GATE", result["reason_code"])


if __name__ == "__main__":
    unittest.main()
