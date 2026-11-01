"""Incremental all-public KAEP marker discovery preserves unknown and source boundaries."""
from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from tools import kaep_public_incremental_cli as inc
from tests.test_kaep_public_locator_cli import repo, comment, OWNER


def owner_list(path, names):
    return [repo(name) for name in names]


def stream(names, pages):
    calls = []
    def fetch(path):
        calls.append(path)
        if path.startswith("/users/"):
            return owner_list(path, names)
        r = path.split("/issues/comments?", 1)[0].split(f"/repos/{OWNER}/", 1)[1]
        page = int(path.rsplit("&page=", 1)[1])
        if r not in pages or page not in pages[r]:
            raise AssertionError(f"unexpected page {r}:{page}")
        return pages[r][page]
    return fetch, calls


def ptr(name, issue, cid, *, marker=True):
    return comment(name, issue, cid, kaep=marker)


class PublicIncrementalTests(TestCase):
    def test_baseline_reuses_existing_scanner_and_provides_head_for_ordinary_comment(self):
        get, calls = stream(["devflow"], {"devflow": {
            1: [ptr("devflow", 200, 900, marker=False), ptr("devflow", 503, 899)]}})
        result = inc.discover_incremental(fetch=get)
        self.assertEqual(result["status"], "BOUNDED_INCREMENTAL_BASELINE")
        self.assertEqual(result["next_cursor"]["heads"], {f"{OWNER}/devflow": 900})
        self.assertEqual(result["locator_count"], 1)
        self.assertEqual(result["locators"][0]["locator"], "devflow#503@899")
        self.assertFalse(result["can_authorize_execution"])
        self.assertFalse(result["absence_of_work_proven"])
        self.assertFalse(result["comment_edits_tracked"])
        self.assertFalse(result["issue_state_changes_tracked"])
        self.assertEqual(len(calls), 2)

    def test_next_read_stops_at_exact_prior_head_no_historical_rediscovery(self):
        baseline, _ = stream(["devflow"], {
            "devflow": {1: [ptr("devflow", 5, 100, marker=False)]}})
        first = inc.discover_incremental(fetch=baseline)
        incoming, calls = stream(["devflow"], {"devflow": {1: [
            ptr("devflow", 20, 103), ptr("devflow", 20, 102, marker=False),
            ptr("devflow", 19, 101), ptr("devflow", 5, 100, marker=False),
            ptr("devflow", 4, 90),
        ]}})
        out = inc.discover_incremental(prior=first["next_cursor"], fetch=incoming)
        self.assertEqual(out["status"], "BOUNDED_INCREMENTAL_READ")
        self.assertEqual([x["locator"] for x in out["locators"]],
                         ["devflow#19@101", "devflow#20@103"])
        self.assertEqual(out["next_cursor"]["heads"][f"{OWNER}/devflow"], 103)
        self.assertEqual(len(calls), 2)
        self.assertTrue(out["has_unknown_work"])

    def test_when_anchor_lies_on_second_page_really_paginates(self):
        old = inc._checkpoint({f"{OWNER}/devflow": 50})
        first = [ptr("devflow", 100, n) for n in range(160, 60, -1)]
        next_page = [ptr("devflow", 100, 60), ptr("devflow", 101, 50),
                     ptr("devflow", 101, 49)]
        get, calls = stream(["devflow"], {"devflow": {1: first, 2: next_page}})
        report = inc.discover_incremental(prior=old, fetch=get)
        self.assertEqual(report["status"], "BOUNDED_INCREMENTAL_READ")
        self.assertEqual(report["locator_count"], 101)
        self.assertEqual(report["next_cursor"]["heads"][f"{OWNER}/devflow"], 160)
        self.assertTrue(calls[-1].endswith("&page=2"))

    def test_prior_head_missing_on_short_page_never_advances(self):
        old = inc._checkpoint({f"{OWNER}/devflow": 777})
        get, _ = stream(["devflow"], {"devflow": {1: [
            ptr("devflow", 13, 800), ptr("devflow", 13, 790)]}})
        r = inc.discover_incremental(prior=old, fetch=get)
        self.assertEqual(r["status"], "PARTIAL_UNKNOWN")
        self.assertIsNone(r["next_cursor"])
        self.assertIn("PRIOR_COMMENT_HEAD_MISSING",
                      [x["reason_code"] for x in r["incomplete_scopes"]])
        self.assertFalse(r["cursor_advanced"])
        self.assertTrue(r["has_unknown_work"])

    def test_zero_comment_head_and_new_public_repo_baseline(self):
        old = inc._checkpoint({f"{OWNER}/empty": 0})
        get, _ = stream(["empty", "new"], {
            "empty": {1: [ptr("empty", 1, 9)]},
            "new": {1: [ptr("new", 2, 8)]}})
        r = inc.discover_incremental(prior=old, fetch=get)
        self.assertEqual(r["status"], "BOUNDED_INCREMENTAL_READ")
        self.assertEqual(r["locator_count"], 2)
        self.assertEqual(r["next_cursor"]["heads"],
                         {f"{OWNER}/empty": 9, f"{OWNER}/new": 8})

    def test_public_repo_removed_is_unknown_and_never_advances(self):
        old = inc._checkpoint({f"{OWNER}/gone": 6, f"{OWNER}/stay": 9})
        get, _ = stream(["stay"], {"stay": {1: [ptr("stay", 1, 9)]}})
        r = inc.discover_incremental(prior=old, fetch=get)
        self.assertEqual(r["status"], "PARTIAL_UNKNOWN")
        self.assertIsNone(r["next_cursor"])
        self.assertIn("PREVIOUS_PUBLIC_REPOSITORY_MISSING",
                      [x["reason_code"] for x in r["incomplete_scopes"]])

    def test_page_limit_gap_never_rotates_checkpoint(self):
        old = inc._checkpoint({f"{OWNER}/devflow": 1})
        get, _ = stream(["devflow"], {"devflow": {
            1: [ptr("devflow", 1, n) for n in range(200, 100, -1)]}})
        r = inc.discover_incremental(prior=old, fetch=get, max_comment_pages=1)
        self.assertEqual(r["status"], "PARTIAL_UNKNOWN")
        self.assertIsNone(r["next_cursor"])
        self.assertEqual(r["incomplete_scopes"][0]["reason_code"], "COMMENT_PAGE_CAP")

    def test_page_read_error_never_advances_and_redacts_secret(self):
        old = inc._checkpoint({f"{OWNER}/devflow": 1})
        def get(path):
            if path.startswith("/users/"):
                return [repo("devflow")]
            raise OSError("private access-token debug")
        r = inc.discover_incremental(prior=old, fetch=get)
        self.assertEqual(r["status"], "PARTIAL_UNKNOWN")
        self.assertIsNone(r["next_cursor"])
        self.assertNotIn("private access-token debug", json.dumps(r))

    def test_cursor_invalid_private_foreign_wrong_schema_duplicates(self):
        for cursor in [
            {"schema_version": inc.CURSOR_SCHEMA, "owner": OWNER,
             "public_only": True, "heads": {f"{OWNER}/bad": -1}},
            {"schema_version": inc.CURSOR_SCHEMA, "owner": OWNER,
             "public_only": True, "heads": {"outsider/repo": 99}},
            {"schema_version": inc.CURSOR_SCHEMA, "owner": OWNER,
             "public_only": True, "heads": {f"{OWNER}/a": True}},
            {"schema_version": "unknown", "owner": OWNER,
             "public_only": True, "heads": {}},
            {"schema_version": inc.CURSOR_SCHEMA, "owner": OWNER,
             "public_only": False, "heads": {}},
        ]:
            with self.subTest(cursor=cursor), self.assertRaisesRegex(
                    Exception, "INVALID_PUBLIC_CURSOR"):
                inc.discover_incremental(prior=cursor,
                                         fetch=lambda _: self.fail("called network"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dup.json"
            path.write_text('{"schema_version":"x","schema_version":"x"}')
            with (mock.patch("sys.stdout", new_callable=io.StringIO) as out):
                rc = inc.main(["--cursor-in", str(path)])
            self.assertEqual(rc, 2)
            self.assertEqual(json.loads(out.getvalue())["status"], "BLOCKED")

    def test_full_and_incremental_reuse_identical_public_comment_contract(self):
        from tools import kaep_public_locator_cli as scanner
        repo_name = f"{OWNER}/devflow"
        current = [ptr("devflow", 20, 103), ptr("devflow", 21, 102, marker=False),
                   ptr("devflow", 19, 101)]
        fetch, _ = stream(["devflow"], {"devflow": {1: current}})
        with mock.patch.object(scanner, "_validated_locator_candidate",
                               wraps=scanner._validated_locator_candidate) as validator:
            full = scanner.discover(fetch=fetch)
            delta = inc.discover_incremental(
                prior=inc._checkpoint({repo_name: 100}), fetch=fetch)
        self.assertEqual(validator.call_count, 2 * len(current))
        self.assertEqual(full["locators"], delta["locators"])
        self.assertEqual(full["locator_count"], delta["locator_count"])
        self.assertFalse(full["can_authorize_execution"])
        self.assertFalse(delta["can_authorize_execution"])

    def test_not_a_raw_issue_body_or_trusted_root(self):
        get, _ = stream(["devflow"], {"devflow": {
            1: [ptr("devflow", 500, 5000)]}})
        out = inc.discover_incremental(fetch=get)
        raw = json.dumps(out)
        for text in ("json payload secret", "Authorization", "private token"):
            self.assertNotIn(text, raw)
        self.assertTrue(out["requires_strict_original_issue_validation"])
        self.assertFalse(out["recipient_pickup_proven"])
        self.assertFalse(out["complete_source_universe"])
        self.assertFalse(out["can_authorize_execution"])

    def test_default_no_local_persistence_and_basic_cli_result(self):
        f, _ = stream(["devflow"], {"devflow": {
            1: [ptr("devflow", 8, 44)]}})
        original = inc.discover_incremental
        with (mock.patch.object(inc.locator, "_gh_get", side_effect=f),
              mock.patch.object(inc, "discover_incremental",
                                wraps=inc.discover_incremental) as spy,
              mock.patch("sys.stdout", new_callable=io.StringIO) as out):
            # The main uses its own function's fetch default, injected via
            # explicit wrapper to avoid changing the production default.
            spy.side_effect = lambda **kw: original(fetch=f, **kw)
            rc = inc.main(["--format", "json"])
        self.assertEqual(rc, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["status"], "BOUNDED_INCREMENTAL_BASELINE")
        self.assertIn("next_cursor", data)
        self.assertEqual(spy.call_count, 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
