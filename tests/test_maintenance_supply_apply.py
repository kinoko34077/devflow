import argparse
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import maintenance_audit as cli
from tools import maintenance_supply as ms


OWNER_BODY = "owner body"
OWNER_SHA = cli.canonical_body_sha256(OWNER_BODY)
OBSERVED_AT = "2026-10-01T00:00:00Z"
ATTEMPT_ID = "attempt-p5-apply"


def _admission():
    return {
        "task": "o/r#7",
        "task_body_sha256": OWNER_SHA,
        "task_work_status": "READY_FOR_IMPLEMENTATION",
        "entry_ref": "https://github.com/o/r/issues/7",
        "scope_ready": True,
        "blocked": False,
        "requires_user_confirmation": False,
        "conflict_keys": ["component:o/r:maintenance"],
        "roles": [
            {
                "role": "implementer",
                "next_action_tag": "IMPLEMENT",
            }
        ],
    }


def _control_body():
    candidate = json.dumps(
        _admission(),
        indent=4,
        ensure_ascii=False,
    ).replace("\n", "\n    ")
    return (
        "## Repository\n\n"
        "`o/r`\n\n"
        "## Repository State\n\n"
        "`ACTIVE`\n\n"
        "## Next Action\n\n"
        "`[IMPLEMENT] bounded maintenance`\n\n"
        "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_BEGIN -->\n"
        "{\n"
        '  "schema_version": 1,\n'
        '  "source_ref": "kinoko34077/devflow#1",\n'
        '  "repository": "o/r",\n'
        '  "candidates": [\n'
        f"    {candidate}\n"
        "  ]\n"
        "}\n"
        "<!-- DEVFLOW_EXECUTION_CANDIDATES_V1_END -->\n\n"
        "<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_BEGIN -->\n"
        "{\n"
        '  "schema_version": "execution-portfolio-metadata.v1",\n'
        '  "source_ref": "kinoko34077/devflow#1",\n'
        '  "repository": "o/r",\n'
        '  "entries": []\n'
        "}\n"
        "<!-- DEVFLOW_EXECUTION_PORTFOLIO_METADATA_V1_END -->\n"
    )


class FakePublishTransport:
    def __init__(self):
        self.control_body = _control_body()
        self.events = []
        self.transitions = []

    def get_issue(self, repository, number):
        if (repository, number) == ("kinoko34077/devflow", 1):
            return {
                "state": "open",
                "title": "[REPO] r",
                "body": self.control_body,
                "html_url": (
                    "https://github.com/kinoko34077/devflow/issues/1"
                ),
                "author_association": "OWNER",
            }
        if (repository, number) == ("o/r", 7):
            return {
                "state": "open",
                "title": "maintenance owner",
                "body": OWNER_BODY,
                "html_url": "https://github.com/o/r/issues/7",
                "author_association": "OWNER",
            }
        raise AssertionError((repository, number))

    def update_control_body(
        self,
        repository,
        control_ref,
        expected_body_sha256,
        body,
    ):
        self.events.append("update")
        if repository != "o/r":
            raise AssertionError(repository)
        if control_ref != "kinoko34077/devflow#1":
            raise AssertionError(control_ref)
        if (
            cli.canonical_body_sha256(self.control_body)
            != expected_body_sha256
        ):
            return False
        self.control_body = body
        return True

    def get_control(self, repository, control_ref):
        self.events.append("readback")
        return {"body": self.control_body}

    def post_supply_transition(self, transition):
        self.events.append("comment")
        self.transitions.append(transition)
        return True


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _args(output, *, apply):
    return argparse.Namespace(
        repository="o/r",
        control=1,
        owner="o/r#7",
        work_class="sync-check",
        attempt_id=ATTEMPT_ID,
        token_env="MAINTENANCE_SUPPLY_TOKEN",
        observed_at=OBSERVED_AT,
        output=str(output),
        apply=apply,
    )


def _published_body(transport):
    control_snapshot, control_body, admission = (
        cli._control_supply_snapshot(
            transport,
            "o/r",
            "kinoko34077/devflow#1",
            owner_ref="o/r#7",
            observed_at=OBSERVED_AT,
            attempt_id=ATTEMPT_ID,
        )
    )
    owner_snapshot = cli._owner_supply_snapshot(
        transport,
        "o/r",
        "o/r#7",
        admission,
    )
    report_id = "sha256:" + hashlib.sha256(
        b"o/r\0o/r#7\0sync-check"
    ).hexdigest()
    desired = ms.build_existing_owner_candidate(
        {
            "action": "PUBLISH_EXISTING_OWNER",
            "report_id": report_id,
            "disposition": "AUTO_ADVANCE",
            "work_class": "sync-check",
            "owner_ref": "o/r#7",
            "reason_codes": ("EXISTING_OWNER_SUPPLY",),
        },
        owner_snapshot,
        control_snapshot,
    )
    edited, changed = ms.reconcile_control_projection_body(
        control_body,
        desired,
        task_ref="o/r#7",
    )
    if not changed:
        raise AssertionError("fixture must require initial publication")
    return edited


class MaintenanceSupplyApplyPathTests(unittest.TestCase):
    def test_transport_posts_compact_transition_to_209(self):
        requests = []

        def opener(request, timeout=0):
            requests.append(request)
            return FakeResponse(
                {
                    "id": 123,
                    "body": "transition",
                    "html_url": (
                        "https://github.com/kinoko34077/"
                        "devflow/issues/209#issuecomment-123"
                    ),
                }
            )

        transport = cli._SyncCheckGitHubTransport(
            "write-token",
            opener=opener,
        )
        self.assertTrue(
            transport.post_supply_transition("transition")
        )
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.method, "POST")
        self.assertTrue(
            request.full_url.endswith(
                "/repos/kinoko34077/devflow/issues/209/comments"
            )
        )
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"body": "transition"},
        )

    def test_material_apply_updates_then_readbacks_then_comments(self):
        transport = FakePublishTransport()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "result.json"
            with (
                mock.patch.object(
                    cli,
                    "_SyncCheckGitHubTransport",
                    return_value=transport,
                ),
                mock.patch.dict(
                    os.environ,
                    {"MAINTENANCE_SUPPLY_TOKEN": "write-token"},
                    clear=False,
                ),
            ):
                rc = cli._publish_supply(
                    _args(output, apply=True)
                )
            payload = json.loads(
                output.read_text(encoding="utf-8")
            )

        self.assertEqual(rc, 0)
        self.assertEqual(
            transport.events,
            ["update", "readback", "comment"],
        )
        self.assertEqual(len(transport.transitions), 1)
        self.assertIn(
            "## Stage-2 maintenance supply transition",
            transport.transitions[0],
        )
        self.assertIn("- action: **published**", transport.transitions[0])
        self.assertTrue(payload["applied"])

    def test_dry_run_does_not_write_or_comment(self):
        transport = FakePublishTransport()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "result.json"
            with (
                mock.patch.object(
                    cli,
                    "_SyncCheckGitHubTransport",
                    return_value=transport,
                ),
                mock.patch.dict(
                    os.environ,
                    {"MAINTENANCE_SUPPLY_TOKEN": "write-token"},
                    clear=False,
                ),
            ):
                rc = cli._publish_supply(
                    _args(output, apply=False)
                )
        self.assertEqual(rc, 0)
        self.assertEqual(transport.events, [])
        self.assertEqual(transport.transitions, [])

    def test_no_change_apply_does_not_comment(self):
        transport = FakePublishTransport()
        transport.control_body = _published_body(transport)
        transport.events.clear()
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "result.json"
            with (
                mock.patch.object(
                    cli,
                    "_SyncCheckGitHubTransport",
                    return_value=transport,
                ),
                mock.patch.dict(
                    os.environ,
                    {"MAINTENANCE_SUPPLY_TOKEN": "write-token"},
                    clear=False,
                ),
            ):
                rc = cli._publish_supply(
                    _args(output, apply=True)
                )
        self.assertEqual(rc, 0)
        self.assertEqual(transport.events, [])
        self.assertEqual(transport.transitions, [])


if __name__ == "__main__":
    unittest.main()
