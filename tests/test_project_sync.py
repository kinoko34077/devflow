import json
import tempfile
import unittest
from pathlib import Path

from scripts import project_sync


class ParseTests(unittest.TestCase):
    def test_parse_exact_sections_lf_crlf_and_backticks(self):
        body = "## Repository\r\n\r\n`kinoko34077/demo`\r\n\r\n## Priority\r\n\r\nP1\r\n\r\n## Not Priority Detail\r\n\r\nignore"
        sections = project_sync.parse_sections(body)
        self.assertEqual(sections["Repository"], "kinoko34077/demo")
        self.assertEqual(sections["Priority"], "P1")
        self.assertNotIn("Not Priority", sections)

    def test_desired_fields_closed_overrides_status(self):
        issue = {"state": "closed", "body": "## Work Status\n\nIMPLEMENTING\n\n## Type\n\nINFRA\n\n## Repository\n\n`kinoko34077/demo`"}
        fields = project_sync.desired_project_fields(issue)
        self.assertEqual(fields["Status"], "DONE")
        self.assertEqual(fields["Work Type"], "INFRA")
        self.assertEqual(fields["Managed Repository"], "kinoko34077/demo")

    def test_missing_sections_are_not_guessed(self):
        issue = {"state": "open", "body": "## Repository\n\nkinoko34077/demo"}
        self.assertEqual(project_sync.desired_project_fields(issue), {"Managed Repository": "kinoko34077/demo"})

    def test_invalid_select_values_are_reported(self):
        errs = project_sync.validate_select_values({"Priority": "P9", "Risk": "LOW"})
        self.assertEqual(len(errs), 1)
        self.assertIn("Priority", errs[0])


class DiscoveryTests(unittest.TestCase):
    def test_exact_field_matching_rejects_duplicates(self):
        fields = [{"id": "1", "name": "Risk", "kind": "single"}, {"id": "2", "name": "Risk", "kind": "single"}]
        with self.assertRaises(project_sync.ConfigError):
            project_sync.require_unique_named(fields, "Risk")

    def test_require_option_rejects_missing_and_duplicate(self):
        field = {"name": "Priority", "options": [{"id": "x", "name": "P1"}, {"id": "y", "name": "P1"}]}
        with self.assertRaises(project_sync.ConfigError):
            project_sync.require_option(field, "P1")
        with self.assertRaises(project_sync.ConfigError):
            project_sync.require_option({"name": "Priority", "options": []}, "P1")

    def test_graphql_pagination_collects_all_nodes(self):
        pages = [
            {"nodes": [{"id": "1"}], "pageInfo": {"hasNextPage": True, "endCursor": "A"}},
            {"nodes": [{"id": "2"}], "pageInfo": {"hasNextPage": False, "endCursor": None}},
        ]
        calls = []
        def fetch(cursor):
            calls.append(cursor)
            return pages[len(calls)-1]
        nodes = project_sync.collect_connection(fetch)
        self.assertEqual([n["id"] for n in nodes], ["1", "2"])
        self.assertEqual(calls, [None, "A"])


class CompareTests(unittest.TestCase):
    def test_compare_match_drift_and_not_applicable(self):
        desired = {"Priority": "P1", "Next Action": "Do thing [VERIFY]"}
        current = {"Priority": "P2", "Next Action": "Do thing [VERIFY]", "Risk": "LOW"}
        result = project_sync.compare_fields(desired, current)
        self.assertEqual(result["Priority"], "DRIFT")
        self.assertEqual(result["Next Action"], "MATCH")
        self.assertEqual(result["Risk"], "NOT_APPLICABLE")

    def test_mutation_plan_only_contains_drift(self):
        desired = {"Priority": "P1", "Risk": "LOW"}
        current = {"Priority": "P1", "Risk": "HIGH"}
        self.assertEqual(project_sync.plan_field_mutations(desired, current), {"Risk": "LOW"})

    def test_verify_missing_membership_does_not_plan_add(self):
        self.assertEqual(project_sync.compare_membership(False, mode="verify"), "DRIFT")
        self.assertFalse(project_sync.should_add_missing_item(False, mode="verify"))
        self.assertTrue(project_sync.should_add_missing_item(False, mode="reconcile"))


class HealthTests(unittest.TestCase):
    def test_health_issue_detection(self):
        self.assertTrue(project_sync.is_health_issue({"title": "[SYSTEM] GitHub Project Sync Health"}))
        self.assertFalse(project_sync.is_health_issue({"title": "[REPO] demo"}))

    def test_health_report_redacts_secret_and_sets_codex_required(self):
        report = project_sync.render_health_report(
            result="FAIL", mode="verify",
            project={"owner": "kinoko34077", "number": 1, "title": "KiNoTch. Development Control"},
            coverage={"canonical_issues": 2, "project_items": 1, "drift_fields": 1, "errors": 1},
            messages=["authorization failed for token supersecret"], run_url="https://github.com/x/actions/runs/1",
            direct_requirement="CODEX_REQUIRED", direct_reason="API/UI mismatch", secrets=["supersecret"],
        )
        self.assertNotIn("supersecret", report)
        self.assertIn("[REDACTED]", report)
        self.assertIn("CODEX_REQUIRED", report)

    def test_runtime_default_repository_is_current_identity(self):
        cfg = project_sync.RuntimeConfig.from_env({})
        self.assertEqual(cfg.repository, "kinoko34077/devflow")
        self.assertEqual(cfg.repository, project_sync.DEFAULT_REPOSITORY)

    def test_missing_projects_token_is_not_configured(self):
        env = {"GITHUB_TOKEN": "repo-token", "GITHUB_REPOSITORY": "kinoko34077/devflow"}
        cfg = project_sync.RuntimeConfig.from_env(env)
        self.assertFalse(cfg.project_token)
        self.assertEqual(project_sync.result_for_missing_project_token(), "NOT_CONFIGURED")


class WorkflowTextTests(unittest.TestCase):
    def test_workflow_has_required_triggers_and_no_schedule(self):
        path = Path(__file__).parents[1] / ".github" / "workflows" / "project-sync.yml"
        text = path.read_text(encoding="utf-8")
        self.assertIn("issues:", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("PROJECTS_TOKEN", text)
        self.assertNotIn("schedule:", text)
        self.assertIn("issues: write", text)
        self.assertIn("event-sync", text)
        self.assertIn("inputs.mode", text)
        self.assertIn("inputs.issue_number", text)


class ClientAndSyncTests(unittest.TestCase):
    def test_graphql_client_raises_on_errors_without_leaking_token(self):
        calls = []
        def transport(url, headers, payload):
            calls.append((url, headers, payload))
            return {"errors": [{"message": "denied"}]}
        client = project_sync.GitHubGraphQL("very-secret", transport=transport)
        with self.assertRaises(project_sync.APIError) as cm:
            client.query("query { viewer { login } }")
        self.assertNotIn("very-secret", str(cm.exception))
        self.assertEqual(calls[0][0], "https://api.github.com/graphql")

    def test_rest_list_issues_paginates_and_skips_pull_requests(self):
        responses = [[{"number": 1, "title": "one"}, {"number": 2, "pull_request": {}, "title": "pr"}], [{"number": 3, "title": "three"}], []]
        calls = []
        def transport(method, url, headers, payload):
            calls.append(url)
            return responses[len(calls)-1]
        rest = project_sync.GitHubREST("repo-token", "kinoko34077/devflow", transport=transport)
        issues = rest.list_issues(state="all", per_page=2)
        self.assertEqual([i["number"] for i in issues], [1, 3])
        self.assertEqual(len(calls), 2)

    def test_discover_project_resolves_fields_items_and_options(self):
        class FakeGraphQL:
            def get_project_identity(self, owner, number):
                return {"id": "P", "title": project_sync.PROJECT_TITLE, "public": False}
            def get_project_fields(self, project_id):
                return [
                    {"id": "F_STATUS", "name": "Status", "kind": "single", "options": [{"id": "O_DONE", "name": "DONE"}, {"id": "O_IMPL", "name": "IMPLEMENTING"}]},
                    {"id": "F_PRIORITY", "name": "Priority", "kind": "single", "options": [{"id": "O_P1", "name": "P1"}]},
                    {"id": "F_RISK", "name": "Risk", "kind": "single", "options": [{"id": "O_LOW", "name": "LOW"}]},
                    {"id": "F_TYPE", "name": "Work Type", "kind": "single", "options": [{"id": "O_INFRA", "name": "INFRA"}]},
                    {"id": "F_RS", "name": "Repository State", "kind": "single", "options": [{"id": "O_ACTIVE", "name": "ACTIVE"}]},
                    {"id": "F_REPO", "name": "Managed Repository", "kind": "text", "options": []},
                    {"id": "F_NEXT", "name": "Next Action", "kind": "text", "options": []},
                    {"id": "F_SHA", "name": "Audit SHA", "kind": "text", "options": []},
                ]
            def get_project_items(self, project_id):
                return [{"id": "I1", "content_id": "ISSUE1", "number": 1, "repository": "kinoko34077/devflow", "fields": {"Priority": "P1"}}]
        snap = project_sync.discover_project(FakeGraphQL(), "kinoko34077", 1)
        self.assertEqual(snap.id, "P")
        self.assertEqual(snap.fields["Priority"].options["P1"], "O_P1")
        self.assertEqual(snap.items_by_content_id["ISSUE1"].fields["Priority"], "P1")

    def test_sync_one_verify_is_read_only_and_reconcile_mutates_only_drift(self):
        fields = {
            "Priority": project_sync.ProjectField("F_PRIORITY", "Priority", "single", {"P1": "O_P1", "P2": "O_P2"}),
            "Risk": project_sync.ProjectField("F_RISK", "Risk", "single", {"LOW": "O_LOW"}),
        }
        item = project_sync.ProjectItem("ITEM", "ISSUE", 9, "kinoko34077/devflow", {"Priority": "P2", "Risk": "LOW"})
        snap = project_sync.ProjectSnapshot("P", project_sync.PROJECT_TITLE, False, fields, {"ISSUE": item})
        issue = {"node_id": "ISSUE", "number": 9, "title": "x", "state": "open", "body": "## Priority\n\nP1\n\n## Risk\n\nLOW"}
        class FakeGraphQL:
            def __init__(self): self.updates = []
            def update_single_select(self, *args): self.updates.append(args)
            def update_text(self, *args): self.updates.append(args)
            def add_item(self, *args): raise AssertionError("not missing")
        gql = FakeGraphQL()
        r_verify = project_sync.sync_one_issue(issue, snap, gql, mode="verify")
        self.assertEqual(gql.updates, [])
        self.assertEqual(r_verify["fields"]["Priority"], "DRIFT")
        r_rec = project_sync.sync_one_issue(issue, snap, gql, mode="reconcile")
        self.assertEqual(len(gql.updates), 1)
        self.assertEqual(gql.updates[0][-1], "O_P1")
        self.assertEqual(r_rec["mutations"], 1)

    def test_sync_one_adds_missing_item_only_for_reconcile(self):
        fields = {"Priority": project_sync.ProjectField("F_PRIORITY", "Priority", "single", {"P1": "O_P1"})}
        empty = project_sync.ProjectSnapshot("P", project_sync.PROJECT_TITLE, False, fields, {})
        issue = {"node_id": "ISSUE", "number": 9, "title": "x", "state": "open", "body": "## Priority\n\nP1"}
        class FakeGraphQL:
            def __init__(self): self.adds = []; self.updates = []
            def add_item(self, project, content): self.adds.append((project, content)); return "NEWITEM"
            def update_single_select(self, *args): self.updates.append(args)
            def update_text(self, *args): self.updates.append(args)
        gql = FakeGraphQL()
        project_sync.sync_one_issue(issue, empty, gql, mode="verify")
        self.assertEqual(gql.adds, [])
        project_sync.sync_one_issue(issue, empty, gql, mode="reconcile")
        self.assertEqual(gql.adds, [("P", "ISSUE")])
        self.assertEqual(len(gql.updates), 1)

    def test_select_canonical_issues_includes_open_plus_project_tracked_closed(self):
        issues = [
            {"number": 1, "node_id": "A", "title": "[REPO] a", "state": "open", "body": ""},
            {"number": 2, "node_id": "B", "title": "old", "state": "closed", "body": ""},
            {"number": 3, "node_id": "C", "title": "not tracked", "state": "closed", "body": ""},
            {"number": 4, "node_id": "D", "title": project_sync.HEALTH_TITLE, "state": "open", "body": ""},
        ]
        selected = project_sync.select_canonical_issues(issues, {"B": object()})
        self.assertEqual([i["number"] for i in selected], [1, 2])

    def test_upsert_health_issue_creates_and_closes_system_issue(self):
        class FakeREST:
            def __init__(self): self.created = []; self.updated = []
            def find_issue_by_title(self, title): return None
            def create_issue(self, title, body): self.created.append((title, body)); return {"number": 50, "title": title, "state": "open"}
            def update_issue(self, number, body=None, state=None): self.updated.append((number, body, state)); return {"number": number, "title": project_sync.HEALTH_TITLE, "state": state or "open"}
        rest = FakeREST()
        project_sync.upsert_health_issue(rest, "health body")
        self.assertEqual(rest.created[0][0], project_sync.HEALTH_TITLE)
        self.assertIn((50, None, "closed"), rest.updated)


class RuntimeFlowTests(unittest.TestCase):
    def test_discover_project_rejects_public_or_wrong_options(self):
        class Fake:
            def get_project_identity(self, owner, number): return {"id": "P", "title": project_sync.PROJECT_TITLE, "public": True}
            def get_project_fields(self, pid): return []
            def get_project_items(self, pid): return []
        with self.assertRaises(project_sync.ConfigError):
            project_sync.discover_project(Fake(), project_sync.PROJECT_OWNER, 1)

    def test_missing_project_token_writes_not_configured_health(self):
        class FakeREST:
            def __init__(self): self.body = None
            def find_issue_by_title(self, title): return {"number": 50, "title": title, "state": "closed"}
            def update_issue(self, number, body=None, state=None): self.body = body; return {"number": number}
        cfg = project_sync.RuntimeConfig("kinoko34077/devflow", "", "repo-token")
        rest = FakeREST()
        code = project_sync.run_sync("verify", cfg, rest=rest, gql=None, issue_number=None, event_issue=None, run_url="run")
        self.assertEqual(code, 2)
        self.assertIn("NOT_CONFIGURED", rest.body)
        self.assertIn("PROJECTS_TOKEN", rest.body)

    def test_health_event_is_skipped_before_project_access(self):
        cfg = project_sync.RuntimeConfig("kinoko34077/devflow", "", "repo-token")
        code = project_sync.run_sync("event-sync", cfg, rest=None, gql=None, issue_number=None, event_issue={"title": project_sync.HEALTH_TITLE}, run_url="run")
        self.assertEqual(code, 0)

    def test_verify_all_reports_drift_without_mutation(self):
        issue = {"number": 9, "node_id": "ISSUE", "title": "x", "state": "open", "body": "## Priority\n\nP1"}
        snap = project_sync.ProjectSnapshot("P", project_sync.PROJECT_TITLE, False, {"Priority": project_sync.ProjectField("F", "Priority", "single", {"P1": "O1"})}, {"ISSUE": project_sync.ProjectItem("I", "ISSUE", 9, "kinoko34077/devflow", {"Priority": "P2"})})
        class FakeGQL:
            def update_single_select(self, *a): raise AssertionError
            def update_text(self, *a): raise AssertionError
            def add_item(self, *a): raise AssertionError
        summary = project_sync.process_issues([issue], snap, FakeGQL(), mode="verify")
        self.assertEqual(summary["drift_fields"], 1)
        self.assertEqual(summary["mutations"], 0)

    def test_health_item_is_reported_and_reconcile_deletes_it(self):
        health = {"number": 50, "node_id": "HEALTH", "title": project_sync.HEALTH_TITLE, "state": "closed", "body": ""}
        snap = project_sync.ProjectSnapshot("P", project_sync.PROJECT_TITLE, False, {}, {"HEALTH": project_sync.ProjectItem("HI", "HEALTH", 50, "kinoko34077/devflow", {})})
        class FakeGQL:
            def __init__(self): self.deleted = []
            def delete_item(self, p, i): self.deleted.append((p, i))
        gql = FakeGQL()
        self.assertEqual(project_sync.ensure_health_not_project_item(health, snap, gql, mode="reconcile"), "REPAIRED")
        self.assertEqual(gql.deleted, [("P", "HI")])

    def test_load_event_issue_reads_issue_payload(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "event.json"
            path.write_text(json.dumps({"issue": {"number": 7, "title": "x"}}), encoding="utf-8")
            self.assertEqual(project_sync.load_event_issue(str(path))["number"], 7)


class StructuralValidationTests(unittest.TestCase):
    def test_project_field_kind_mismatch_fails(self):
        class FakeGraphQL:
            def get_project_identity(self, owner, number): return {"id": "P", "title": project_sync.PROJECT_TITLE, "public": False}
            def get_project_fields(self, project_id):
                return [{"id": name, "name": name, "kind": "text", "options": []} for name in project_sync.EXPECTED_FIELDS]
            def get_project_items(self, project_id): return []
        with self.assertRaises(project_sync.ConfigError):
            project_sync.discover_project(FakeGraphQL(), project_sync.PROJECT_OWNER, project_sync.PROJECT_NUMBER)

    def test_duplicate_option_names_fail(self):
        class FakeGraphQL:
            def get_project_identity(self, owner, number): return {"id": "P", "title": project_sync.PROJECT_TITLE, "public": False}
            def get_project_fields(self, project_id):
                out = []
                for name in project_sync.EXPECTED_FIELDS:
                    if name in project_sync.SELECT_OPTIONS:
                        opts = [{"id": f"{name}-1", "name": v} for v in project_sync.SELECT_OPTIONS[name]]
                        if name == "Priority": opts.append({"id": "dup", "name": "P1"})
                        out.append({"id": name, "name": name, "kind": "single", "options": opts})
                    else:
                        out.append({"id": name, "name": name, "kind": "text", "options": []})
                return out
            def get_project_items(self, project_id): return []
        with self.assertRaises(project_sync.ConfigError):
            project_sync.discover_project(FakeGraphQL(), project_sync.PROJECT_OWNER, project_sync.PROJECT_NUMBER)


if __name__ == "__main__":
    unittest.main()
