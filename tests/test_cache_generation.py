import copy
import unittest

from tools import human_portfolio_cache
from tools import repository_projection_cache
from tools.cache_generation import (
    generation_material,
    recompute_generation_id,
)


class CacheGenerationTests(unittest.TestCase):
    def test_shared_generation_material_is_non_mutating_and_removes_only_id(self):
        payload = {
            "generation_id": "sha256:old",
            "repository": "kinoko34077/devflow",
            "nested": {"value": "保持"},
        }
        original = copy.deepcopy(payload)

        self.assertEqual(
            generation_material(payload),
            {
                "repository": "kinoko34077/devflow",
                "nested": {"value": "保持"},
            },
        )
        self.assertEqual(payload, original)

    def test_shared_recompute_matches_both_cache_compatibility_functions(self):
        payload = {
            "generation_id": "sha256:old",
            "repository": "kinoko34077/devflow",
            "nested": {"value": "保持"},
        }

        expected = recompute_generation_id(payload)

        self.assertEqual(expected, human_portfolio_cache.recompute_generation_id(payload))
        self.assertEqual(expected, repository_projection_cache.recompute_generation_id(payload))
        self.assertEqual(payload["generation_id"], "sha256:old")


if __name__ == "__main__":
    unittest.main()

