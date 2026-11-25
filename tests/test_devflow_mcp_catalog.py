"""Catalog admission regressions for the shared release/connection contract."""
from __future__ import annotations

import unittest

from mcp import types

from tools.devflow_mcp_catalog import (
    CatalogError, REQUIRED_CALLS, RESTART_TOOL, admit_catalog, arguments_supported,
)


def tool(name, schema=None, **kwargs):
    return types.Tool(
        name=name, inputSchema=schema if schema is not None else {"type": "object"},
        **kwargs,
    )


def baseline():
    return [tool(name, {
        "type": "object",
        "properties": {k: {"const": v} for k, v in args.items()},
        "required": list(args),
        "additionalProperties": False,
    }) for name, args in REQUIRED_CALLS.items()]


class CatalogAdmissionTests(unittest.TestCase):
    def test_variable_catalog_and_optional_input(self):
        old = baseline() + [tool("old_optional")]
        self.assertIn("old_optional", admit_catalog(old))
        new = baseline()
        new[0] = tool("bootstrap_repository", {
            "type": "object",
            "properties": {
                "repository": {"type": "string"},
                "include_details": {"type": "boolean", "default": False},
            },
            "required": ["repository"],
            "additionalProperties": False,
        })
        new.extend([tool("new_optional"), tool("another_optional")])
        catalog = admit_catalog(new)
        self.assertNotIn("old_optional", catalog)
        self.assertIn("new_optional", catalog)
        self.assertTrue(arguments_supported(catalog["bootstrap_repository"],
                                            {"repository": "kinoko34077/devflow"}))
        self.assertTrue(arguments_supported(catalog["bootstrap_repository"],
                                            {"repository": "kinoko34077/devflow",
                                             "include_details": True}))
        self.assertFalse(arguments_supported(catalog["bootstrap_repository"],
                                             {"repository": "kinoko34077/devflow",
                                              "include_details": "yes"}))

    def test_required_call_cannot_be_removed_or_made_invalid(self):
        with self.assertRaises(CatalogError):
            admit_catalog(baseline()[1:])
        changed = baseline()
        changed[0] = tool("bootstrap_repository", {
            "type": "object",
            "properties": {"repository": {"type": "string"}, "new_required": {}},
            "required": ["repository", "new_required"],
        })
        with self.assertRaises(CatalogError):
            admit_catalog(changed)

    def test_duplicate_reserved_invalid_and_incomplete_catalogs(self):
        for addition in (
            tool("bootstrap_repository"), tool(RESTART_TOOL), tool(" "),
            tool("invalid_schema", {"type": "object", "required": "not-an-array"}),
            tool("declared_write", annotations=types.ToolAnnotations(readOnlyHint=False)),
            tool("declared_destructive", annotations=types.ToolAnnotations(destructiveHint=True)),
        ):
            with self.subTest(name=addition.name), self.assertRaises(CatalogError):
                admit_catalog(baseline() + [addition])
        with self.assertRaises(CatalogError):
            admit_catalog(baseline(), next_cursor="another-page")

    def test_required_external_ref_fails_without_network_resolution(self):
        changed = baseline()
        changed[0] = tool("bootstrap_repository", {
            "type": "object",
            "properties": {"repository": {"$ref": "https://invalid.example/schema.json"}},
            "required": ["repository"],
        })
        with self.assertRaises(CatalogError):
            admit_catalog(changed)

    def test_local_ref_is_supported(self):
        changed = baseline()
        changed[0] = tool("bootstrap_repository", {
            "type": "object",
            "properties": {"repository": {"$ref": "#/$defs/repository"}},
            "$defs": {"repository": {"type": "string"}},
            "required": ["repository"],
        })
        self.assertIn("bootstrap_repository", admit_catalog(changed))

    def test_connection_fixture_uses_same_contract_not_fixed_count(self):
        calls = {"read_version": {}}
        self.assertEqual(set(admit_catalog([tool("read_version")],
                                            required_calls=calls)), {"read_version"})
        self.assertEqual(set(admit_catalog([tool("read_version"), tool("extra")],
                                            required_calls=calls)), {"read_version", "extra"})


if __name__ == "__main__":
    unittest.main()
