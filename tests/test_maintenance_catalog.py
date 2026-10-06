import json
import tempfile
import unittest
from pathlib import Path

from tools import maintenance_catalog as mc


class MaintenanceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.baseline_path = self.root / "common-baseline.v1.yaml"
        self.catalog_path = self.root / "maintenance.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def _write_json(self, path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _baseline(self) -> dict[str, object]:
        return {
            "schema_version": "maintenance-common-baseline.v1",
            "catalog_schema_version": "maintenance-catalog.v1",
            "lenses": [
                {"id": "correctness", "title": "Correctness"},
                {"id": "edge-cases", "title": "Edge Cases"},
                {"id": "reliability-recovery", "title": "Reliability / Recovery"},
                {"id": "security", "title": "Security"},
                {"id": "state-integrity-concurrency", "title": "State Integrity / Concurrency"},
                {"id": "spec-implementation-drift", "title": "Spec / Implementation Drift"},
                {"id": "test-quality", "title": "Test Quality"},
                {"id": "resource-management", "title": "Resource Management"},
                {"id": "dependency-external-assumptions", "title": "Dependency / External Assumptions"},
                {"id": "error-handling", "title": "Error Handling"},
                {"id": "observability", "title": "Observability"},
                {"id": "lifecycle-consistency", "title": "Lifecycle / Issue / PR / Session consistency"},
            ],
            "risk_policy": {
                "LOW": {
                    "general_standard_days": 90,
                    "security_standard_days": 90,
                    "deep_target_days": 180,
                    "cooldown_hours": 168,
                },
                "MEDIUM": {
                    "general_standard_days": 60,
                    "security_standard_days": 45,
                    "deep_target_days": 120,
                    "cooldown_hours": 72,
                },
                "HIGH": {
                    "general_standard_days": 30,
                    "security_standard_days": 21,
                    "deep_target_days": 60,
                    "cooldown_hours": 24,
                },
                "CRITICAL": {
                    "general_standard_days": 14,
                    "security_standard_days": 7,
                    "deep_target_days": 30,
                    "cooldown_hours": 6,
                },
            },
            "freshness_classes": {
                "FAST": {"days": 1},
                "NORMAL": {"days": 7},
                "SLOW": {"days": 30},
            },
            "selector_weights": {
                "never_run": 40,
                "overdue": 20,
                "overdue_2x_bonus": 10,
                "unexecuted_lens": 15,
                "deeper_coverage": 15,
                "source_change": 25,
                "high_risk": 15,
                "critical_risk": 25,
                "finding_reaudit": 20,
                "security_event": 30,
                "external_stale": 20,
                "same_repository_penalty": -10,
                "recent_similar_penalty": -20,
            },
            "common_slots": [
                {
                    "slot_id": f"common.{lens['id']}",
                    "title": lens["title"],
                    "lifecycle": "ACTIVE",
                    "scope": {"kind": "repository", "selector": "."},
                    "lens": lens["id"],
                    "coverage_key": f"common.{lens['id']}",
                    "minimum_depth": "STANDARD",
                    "external_freshness_class": "NORMAL",
                    "description": f"Common {lens['title']} audit",
                }
                for lens in [
                    {"id": "correctness", "title": "Correctness"},
                    {"id": "edge-cases", "title": "Edge Cases"},
                    {"id": "reliability-recovery", "title": "Reliability / Recovery"},
                    {"id": "security", "title": "Security"},
                    {"id": "state-integrity-concurrency", "title": "State Integrity / Concurrency"},
                    {"id": "spec-implementation-drift", "title": "Spec / Implementation Drift"},
                    {"id": "test-quality", "title": "Test Quality"},
                    {"id": "resource-management", "title": "Resource Management"},
                    {"id": "dependency-external-assumptions", "title": "Dependency / External Assumptions"},
                    {"id": "error-handling", "title": "Error Handling"},
                    {"id": "observability", "title": "Observability"},
                    {"id": "lifecycle-consistency", "title": "Lifecycle / Issue / PR / Session consistency"},
                ]
            ],
        }

    def _catalog(self) -> dict[str, object]:
        return {
            "schema_version": "maintenance-catalog.v1",
            "repository": "kinoko34077/example",
            "baseline": "maintenance-common-baseline.v1",
            "rollout": "PILOT",
            "risk_profile": "HIGH",
            "scope_risk_overrides": [],
            "common_slot_overrides": [],
            "repository_slots": [],
        }

    def _load(self):
        self._write_json(self.baseline_path, self._baseline())
        self._write_json(self.catalog_path, self._catalog())
        baseline = mc.load_common_baseline(self.baseline_path)
        catalog = mc.load_repository_catalog(self.catalog_path, baseline)
        return baseline, catalog

    def test_common_baseline_loads_twelve_accepted_lenses(self):
        baseline, _ = self._load()
        self.assertEqual(
            [
                "Correctness",
                "Edge Cases",
                "Reliability / Recovery",
                "Security",
                "State Integrity / Concurrency",
                "Spec / Implementation Drift",
                "Test Quality",
                "Resource Management",
                "Dependency / External Assumptions",
                "Error Handling",
                "Observability",
                "Lifecycle / Issue / PR / Session consistency",
            ],
            [lens.title for lens in baseline.lenses],
        )

    def test_catalog_references_exactly_the_loaded_baseline_version(self):
        baseline, catalog = self._load()
        self.assertEqual(baseline.schema_version, catalog.baseline)

        data = self._catalog()
        data["baseline"] = "maintenance-common-baseline.v2"
        self._write_json(self.baseline_path, self._baseline())
        self._write_json(self.catalog_path, data)
        baseline = mc.load_common_baseline(self.baseline_path)
        with self.assertRaisesRegex(mc.MaintenanceCatalogError, "baseline"):
            mc.load_repository_catalog(self.catalog_path, baseline)

    def test_unknown_schema_version_fails_closed(self):
        self._write_json(self.baseline_path, self._baseline())
        data = self._catalog()
        data["schema_version"] = "maintenance-catalog.v2"
        self._write_json(self.catalog_path, data)
        baseline = mc.load_common_baseline(self.baseline_path)
        with self.assertRaisesRegex(mc.MaintenanceCatalogError, "schema_version"):
            mc.load_repository_catalog(self.catalog_path, baseline)

    def test_unknown_top_level_field_is_rejected(self):
        self._write_json(self.baseline_path, self._baseline())
        data = self._catalog()
        data["surprise"] = True
        self._write_json(self.catalog_path, data)
        baseline = mc.load_common_baseline(self.baseline_path)
        with self.assertRaisesRegex(mc.MaintenanceCatalogError, "unknown"):
            mc.load_repository_catalog(self.catalog_path, baseline)

    def test_duplicate_json_key_is_rejected(self):
        self._write_json(self.baseline_path, self._baseline())
        self.catalog_path.write_text(
            '{"schema_version":"maintenance-catalog.v1",'
            '"schema_version":"maintenance-catalog.v1"}',
            encoding="utf-8",
        )
        baseline = mc.load_common_baseline(self.baseline_path)
        with self.assertRaisesRegex(mc.MaintenanceCatalogError, "duplicate"):
            mc.load_repository_catalog(self.catalog_path, baseline)

    def test_duplicate_slot_id_is_rejected(self):
        self._write_json(self.baseline_path, self._baseline())
        data = self._catalog()
        slot = {
            "slot_id": "repo.parser",
            "title": "Parser",
            "lifecycle": "ACTIVE",
            "scope": {"kind": "component", "selector": "parser"},
            "lens": "correctness",
            "coverage_key": "repo.parser",
            "minimum_depth": "STANDARD",
            "external_freshness_class": "NORMAL",
            "description": "Parser correctness",
        }
        data["repository_slots"] = [slot, dict(slot)]
        self._write_json(self.catalog_path, data)
        baseline = mc.load_common_baseline(self.baseline_path)
        with self.assertRaisesRegex(mc.MaintenanceCatalogError, "duplicate slot_id"):
            mc.load_repository_catalog(self.catalog_path, baseline)

    def test_duplicate_active_coverage_scope_and_lens_is_rejected(self):
        self._write_json(self.baseline_path, self._baseline())
        data = self._catalog()
        base_slot = {
            "title": "Parser",
            "lifecycle": "ACTIVE",
            "scope": {"kind": "component", "selector": "parser"},
            "lens": "correctness",
            "coverage_key": "repo.parser",
            "minimum_depth": "STANDARD",
            "external_freshness_class": "NORMAL",
            "description": "Parser correctness",
        }
        data["repository_slots"] = [
            dict(base_slot, slot_id="repo.parser-a"),
            dict(base_slot, slot_id="repo.parser-b"),
        ]
        self._write_json(self.catalog_path, data)
        baseline = mc.load_common_baseline(self.baseline_path)
        with self.assertRaisesRegex(mc.MaintenanceCatalogError, "duplicate active coverage"):
            mc.load_repository_catalog(self.catalog_path, baseline)

        data["repository_slots"][1]["lifecycle"] = "SUPERSEDED"
        self._write_json(self.catalog_path, data)
        catalog = mc.load_repository_catalog(self.catalog_path, baseline)
        self.assertEqual(2, len(catalog.repository_slots))

    def test_retired_slot_does_not_resolve_as_runnable(self):
        self._write_json(self.baseline_path, self._baseline())
        data = self._catalog()
        data["repository_slots"] = [{
            "slot_id": "repo.retired",
            "title": "Retired",
            "lifecycle": "RETIRED",
            "scope": {"kind": "component", "selector": "old"},
            "lens": "correctness",
            "coverage_key": "repo.retired",
            "minimum_depth": "STANDARD",
            "external_freshness_class": "NORMAL",
            "description": "Old audit",
        }]
        self._write_json(self.catalog_path, data)
        baseline = mc.load_common_baseline(self.baseline_path)
        catalog = mc.load_repository_catalog(self.catalog_path, baseline)
        resolved = mc.resolve_catalog(baseline, catalog)
        self.assertNotIn("repo.retired", {slot.slot_id for slot in resolved})

    def test_repository_override_cannot_remove_all_security_coverage(self):
        self._write_json(self.baseline_path, self._baseline())
        data = self._catalog()
        data["common_slot_overrides"] = [{
            "slot_id": "common.security",
            "lifecycle": "RETIRED",
            "rationale": "not needed",
        }]
        self._write_json(self.catalog_path, data)
        baseline = mc.load_common_baseline(self.baseline_path)
        with self.assertRaisesRegex(mc.MaintenanceCatalogError, "Security"):
            mc.load_repository_catalog(self.catalog_path, baseline)

    def test_unknown_enums_and_scope_kind_are_rejected(self):
        self._write_json(self.baseline_path, self._baseline())
        cases = [
            ("risk_profile", "EXTREME"),
            ("rollout", "AUTO"),
        ]
        baseline = mc.load_common_baseline(self.baseline_path)
        for field, value in cases:
            with self.subTest(field=field):
                data = self._catalog()
                data[field] = value
                self._write_json(self.catalog_path, data)
                with self.assertRaises(mc.MaintenanceCatalogError):
                    mc.load_repository_catalog(self.catalog_path, baseline)

        data = self._catalog()
        data["repository_slots"] = [{
            "slot_id": "repo.bad",
            "title": "Bad",
            "lifecycle": "ACTIVE",
            "scope": {"kind": "planet", "selector": "mars"},
            "lens": "correctness",
            "coverage_key": "repo.bad",
            "minimum_depth": "STANDARD",
            "external_freshness_class": "NORMAL",
            "description": "Bad scope",
        }]
        self._write_json(self.catalog_path, data)
        with self.assertRaisesRegex(mc.MaintenanceCatalogError, "scope"):
            mc.load_repository_catalog(self.catalog_path, baseline)

    def test_catalog_digest_is_stable_across_object_key_order(self):
        baseline, catalog = self._load()
        first = mc.canonical_catalog_digest(baseline, catalog)

        data = self._catalog()
        reordered = {
            "repository_slots": data["repository_slots"],
            "scope_risk_overrides": data["scope_risk_overrides"],
            "risk_profile": data["risk_profile"],
            "rollout": data["rollout"],
            "baseline": data["baseline"],
            "common_slot_overrides": data["common_slot_overrides"],
            "repository": data["repository"],
            "schema_version": data["schema_version"],
        }
        self._write_json(self.catalog_path, reordered)
        second_catalog = mc.load_repository_catalog(self.catalog_path, baseline)
        second = mc.canonical_catalog_digest(baseline, second_catalog)
        self.assertEqual(first, second)
        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
