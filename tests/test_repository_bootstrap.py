import json
import unittest

from tools import repository_bootstrap as rb


START = "<!-- repository-bootstrap:v1:start -->"
END = "<!-- repository-bootstrap:v1:end -->"


def request_payload(**overrides):
    data = {
        "schema": "repository-bootstrap.v1",
        "repository": {
            "owner": "kinoko34077",
            "name": "example-repo",
            "description": "Example repository",
        },
        "classification": {
            "kind": "library",
            "priority": "P2",
            "risk": "MEDIUM",
        },
        "bootstrap": {},
        "initial_content": {
            "readme": "# example-repo\n",
            "specification": None,
            "license": None,
        },
        "issues": [
            {
                "key": "scope",
                "title": "Initial scope",
                "body": "Define the initial scope.",
                "role": "parent",
            }
        ],
        "devflow": {
            "create_control": True,
            "work_status": "WORK_ORDER_READY",
            "repository_state": "ACTIVE",
            "next_action": "[SPECIFY] Define the first implementation slice.",
        },
    }
    for key, value in overrides.items():
        data[key] = value
    return data


def issue_body(payload=None):
    payload = request_payload() if payload is None else payload
    return (
        "Human-readable request context.\n\n"
        f"{START}\n"
        "```json\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n"
        "```\n"
        f"{END}\n"
    )


class RepositoryBootstrapContractTests(unittest.TestCase):
    def test_parse_and_normalize_applies_safe_defaults(self):
        raw = rb.parse_request_body(issue_body())
        request = rb.normalize_request(raw, "[REPO CREATE] example-repo")

        self.assertEqual(request.repository.owner, "kinoko34077")
        self.assertEqual(request.repository.name, "example-repo")
        self.assertEqual(request.repository.visibility, "private")
        self.assertEqual(request.template, "minimal")
        self.assertTrue(request.devflow_managed)
        self.assertIsNone(request.license)
        self.assertTrue(request.create_control)

    def test_explicit_public_visibility_is_preserved(self):
        payload = request_payload()
        payload["repository"]["visibility"] = "public"
        request = rb.normalize_request(
            rb.parse_request_body(issue_body(payload)),
            "[REPO CREATE] example-repo",
        )
        self.assertEqual(request.repository.visibility, "public")

    def test_public_visibility_is_never_inferred_from_description(self):
        payload = request_payload()
        payload["repository"]["description"] = "Public open-source OSS library"
        request = rb.normalize_request(
            rb.parse_request_body(issue_body(payload)),
            "[REPO CREATE] example-repo",
        )
        self.assertEqual(request.repository.visibility, "private")

    def test_unknown_schema_fails_closed(self):
        payload = request_payload(schema="repository-bootstrap.v2")
        with self.assertRaises(rb.BootstrapError):
            rb.normalize_request(
                rb.parse_request_body(issue_body(payload)),
                "[REPO CREATE] example-repo",
            )

    def test_missing_or_duplicate_payload_marker_fails_closed(self):
        with self.assertRaises(rb.BootstrapError):
            rb.parse_request_body("no request payload")

        body = issue_body() + "\n" + issue_body()
        with self.assertRaises(rb.BootstrapError):
            rb.parse_request_body(body)

    def test_title_must_match_repository_name_exactly(self):
        with self.assertRaises(rb.BootstrapError):
            rb.normalize_request(
                rb.parse_request_body(issue_body()),
                "[REPO CREATE] another-repo",
            )

    def test_owner_is_restricted_in_v1(self):
        payload = request_payload()
        payload["repository"]["owner"] = "someone-else"
        with self.assertRaises(rb.BootstrapError):
            rb.normalize_request(
                rb.parse_request_body(issue_body(payload)),
                "[REPO CREATE] example-repo",
            )

    def test_repository_name_validation_rejects_unsafe_or_ambiguous_names(self):
        for name in ("", ".", "..", "bad/name", " bad", "bad ", "x" * 101):
            with self.subTest(name=name):
                payload = request_payload()
                payload["repository"]["name"] = name
                with self.assertRaises(rb.BootstrapError):
                    rb.normalize_request(
                        rb.parse_request_body(issue_body(payload)),
                        f"[REPO CREATE] {name}",
                    )

    def test_invalid_enums_fail_closed(self):
        mutations = [
            ("repository", "visibility", "internal"),
            ("classification", "priority", "P9"),
            ("classification", "risk", "EXTREME"),
            ("bootstrap", "template", "everything"),
            ("devflow", "work_status", "NEW"),
            ("devflow", "repository_state", "BLOCKED"),
        ]
        for section, key, value in mutations:
            with self.subTest(section=section, key=key, value=value):
                payload = request_payload()
                payload[section][key] = value
                with self.assertRaises(rb.BootstrapError):
                    rb.normalize_request(
                        rb.parse_request_body(issue_body(payload)),
                        "[REPO CREATE] example-repo",
                    )

    def test_duplicate_issue_keys_fail_closed(self):
        payload = request_payload()
        payload["issues"].append(
            {
                "key": "scope",
                "title": "Duplicate",
                "body": "Conflicting duplicate key.",
            }
        )
        with self.assertRaises(rb.BootstrapError):
            rb.normalize_request(
                rb.parse_request_body(issue_body(payload)),
                "[REPO CREATE] example-repo",
            )

    def test_control_cannot_be_requested_for_unmanaged_repository(self):
        payload = request_payload()
        payload["bootstrap"]["devflow_managed"] = False
        payload["devflow"]["create_control"] = True
        with self.assertRaises(rb.BootstrapError):
            rb.normalize_request(
                rb.parse_request_body(issue_body(payload)),
                "[REPO CREATE] example-repo",
            )

    def test_trusted_author_associations_are_exact(self):
        for value in ("OWNER", "MEMBER", "COLLABORATOR"):
            with self.subTest(value=value):
                self.assertTrue(rb.is_trusted_association(value))

        for value in ("CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "NONE", "owner", ""):
            with self.subTest(value=value):
                self.assertFalse(rb.is_trusted_association(value))


if __name__ == "__main__":
    unittest.main()
