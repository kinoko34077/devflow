"""Fail-closed Codex Cloud read-only probe contract tests."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from tools.codex_cloud_route_probe import probe


def _make_paths(tmp_path: Path) -> tuple[str, str]:
    cli = tmp_path / "codex.cmd"
    cli.write_text("fake", encoding="utf-8")
    return str(cli), str(tmp_path)


def _response(stdout: str, code: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr="HIDDEN_PRIVATE_DATA")


def test_missing_executable_fails_closed(tmp_path):
    with patch("tools.codex_cloud_route_probe.subprocess.run") as run:
        result = probe(str(tmp_path / "missing"), str(tmp_path))
    assert result.status == "INVALID_LOCAL_TARGET"
    assert result.dispatch_verified is False
    run.assert_not_called()


def test_version_and_zero_tasks_not_environment_proof(tmp_path):
    cli, root = _make_paths(tmp_path)
    with patch("tools.codex_cloud_route_probe.subprocess.run", side_effect=[
        _response("codex-cli 0.155.1\n"), _response('{"tasks":[],"cursor":null}')
    ]) as run:
        result = probe(cli, root)
    assert result.status == "TASK_LIST_ACCESSIBLE_ONLY"
    assert result.task_count == 0
    assert not result.environment_verified and not result.dispatch_verified
    commands = [x.args[0] for x in run.call_args_list]
    assert commands[0][1:] == ["--version"]
    assert commands[1][1:] == ["cloud", "list", "--json"]
    assert all(x.kwargs["shell"] is False for x in run.call_args_list)


def test_success_redacts_task_contents(tmp_path):
    cli, root = _make_paths(tmp_path)
    with patch("tools.codex_cloud_route_probe.subprocess.run", side_effect=[
        _response("codex-cli 0.162.0"), _response(json.dumps({"tasks": [{"name": "PRIVATE_SECRET_DATA"}]}))
    ]):
        result = probe(cli, root)
    assert result.task_count == 1
    assert "PRIVATE_SECRET_DATA" not in str(result)


def test_cli_failure_stops_before_list(tmp_path):
    cli, root = _make_paths(tmp_path)
    with patch("tools.codex_cloud_route_probe.subprocess.run", return_value=_response("secret", 1)) as run:
        result = probe(cli, root)
    assert result.status == "CLI_FAILURE"
    assert result.cli_version is None
    assert run.call_count == 1


def test_bad_task_json_fails_closed(tmp_path):
    cli, root = _make_paths(tmp_path)
    with patch("tools.codex_cloud_route_probe.subprocess.run", side_effect=[
        _response("codex-cli 0.155.1"), _response("{broken")
    ]):
        result = probe(cli, root)
    assert result.status == "INVALID_TASK_LIST"
    assert not result.task_list_accessible


def test_version_must_be_recognized(tmp_path):
    cli, root = _make_paths(tmp_path)
    with patch("tools.codex_cloud_route_probe.subprocess.run", return_value=_response("bogus-setup-token")) as run:
        result = probe(cli, root)
    assert result.status == "UNRECOGNIZED_VERSION"
    assert run.call_count == 1


def test_timeout_does_not_retry_or_submit(tmp_path):
    cli, root = _make_paths(tmp_path)
    with patch("tools.codex_cloud_route_probe.subprocess.run", side_effect=subprocess.TimeoutExpired([cli, "--version"], 1)) as run:
        result = probe(cli, root, timeout_seconds=1)
    assert result.status == "TIMEOUT"
    assert run.call_count == 1


def test_bad_timeout_never_calls_cli(tmp_path):
    cli, root = _make_paths(tmp_path)
    with patch("tools.codex_cloud_route_probe.subprocess.run") as run:
        result = probe(cli, root, timeout_seconds=31)
    assert result.status == "INVALID_LOCAL_TARGET"
    run.assert_not_called()


def test_output_bounded_no_raw_data(tmp_path):
    cli, root = _make_paths(tmp_path)
    with patch("tools.codex_cloud_route_probe.subprocess.run", side_effect=[
        _response("codex-cli 0.155.1"), _response("secret" * 20000)
    ]):
        result = probe(cli, root)
    assert result.status == "OVERSIZED_OUTPUT"
    assert "secret" not in str(result)
