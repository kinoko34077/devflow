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

    def test_repository_projection_cache_is_excluded_from_last_canonical_section(self):
        marker = project_sync.REPOSITORY_PROJECTION_CACHE_MARKER_BEGIN
        end = "<!-- DEVFLOW_REPOSITORY_PROJECTION_V1_END -->"
        payload = (
            "\n\n" + marker + "\n"
            "{" + '"schema_version":"repository-projection-cache.v1",' + '"generation_id":"sha256:test"' + "}\n"
            + end
        )
        cases = [
            (
                "## Next Action\n\n[WAIT] No active work." + payload,
                "Next Action",
                "[WAIT] No active work.",
            ),
            (
                "## Audit Evidence\n\nrun 123 SUCCESS" + payload,
                "Audit Evidence",
                "run 123 SUCCESS",
            ),
        ]
        for body, section, expected in cases:
            with self.subTest(section=section):
                sections = project_sync.parse_sections(body)
                self.assertEqual(sections[section], expected)
                self.assertNotIn("generation_id", sections[section])

    def test_projection_cache_does_not_leak_into_project_text_fields(self):
        body = (
            "## Repository\n\nkinoko34077/demo\n\n"
            "## Next Action\n\n[WAIT] bounded\n\n"
            + project_sync.REPOSITORY_PROJECTION_CACHE_MARKER_BEGIN
            + "\n{\"schema_version\":\"repository-projection-cache.v1\"}\n"
            "<!-- DEVFLOW_REPOSITORY_PROJECTION_V1_END -->"
        )
        fields = project_sync.desired_project_fields({"state": "open", "body": body})
        self.assertEqual(fields["Managed Repository"], "kinoko34077/demo")
        self.assertEqual(fields["Next Action"], "[WAIT] bounded")

    def test_desired_fields_closed_overrides_status(self):
        issue = {"state": "closed", "body": "## Work Status\n\nIMPLEMENTING\n\n## Type\n\nINFRA\n\n## Repository\n\n`kinoko34077/demo`"}
        fields = project_sync.desired_project_fields(issue)
        self.assertEqual(fields["Status"], "DONE")
        self.assertEqual(fields["Work Type"], "INFRA")
        self.assertEqual(fields["Managed Repository"], "kinoko34077/demo")

    def test_wait_control_maps_to_existing_project_status_alias(self):
        issue = {
            "state": "open",
            "body": "## Work Status\n\nWAIT\n\n## Repository\n\n`kinoko34077/demo`",
        }
        fields = project_sync.desired_project_fields(issue)
        self.assertEqual(fields["Status"], "PARKED")
        self.assertEqual(project_sync.validate_select_values(fields), [])

    def test_wait_exception_is_control_only_in_machine_workflow(self):
        workflow = (Path(__file__).parents[1] / ".devflow" / "WORKFLOW.yaml").read_text(encoding="utf-8")
        general_states = workflow.split("  work_states:", 1)[1].split("  repository_states:", 1)[0]
        control = workflow.split("repository_control:", 1)[1].split("repository_bootstrap:", 1)[0]

        self.assertNotIn("- WAIT", general_states)
        self.assertIn("control_only_wait_source_state:", control)
        self.assertIn("value: WAIT", control)
        self.assertIn("general_work_state: false", control)
        self.assertIn("project_status_projection: PARKED", control)

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
                out = []
                for name in project_sync.EXPECTED_FIELDS:
                    if name in project_sync.SELECT_OPTIONS:
                        options = [
                            {"id": f"{name}-{value}", "name": value}
                            for value in project_sync.SELECT_OPTIONS[name]
                        ]
                        out.append({"id": name, "name": name, "kind": "single", "options": options})
                    elif name in project_sync.DATE_FIELDS:
                        out.append({"id": name, "name": name, "kind": "date", "options": []})
                    else:
                        out.append({"id": name, "name": name, "kind": "text", "options": []})
                return out
            def get_project_items(self, project_id):
                return [{"id": "I1", "content_id": "ISSUE1", "number": 1, "repository": "kinoko34077/devflow", "fields": {"Priority": "P1"}}]
        snap = project_sync.discover_project(FakeGraphQL(), "kinoko34077", 1)
        self.assertEqual(snap.id, "P")
        self.assertEqual(snap.fields["Priority"].options["P1"], "Priority-P1")
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
            {"number": 1, "node_id": "A", "title": "[REPO] a", "state": "open", "body": "", "author_association": "OWNER"},
            {"number": 2, "node_id": "B", "title": "old", "state": "closed", "body": "", "author_association": "MEMBER"},
            {"number": 3, "node_id": "C", "title": "not tracked", "state": "closed", "body": "", "author_association": "OWNER"},
            {"number": 4, "node_id": "D", "title": project_sync.HEALTH_TITLE, "state": "open", "body": "", "author_association": "OWNER"},
            {"number": 5, "node_id": "E", "title": "[REPO] spoof", "state": "open", "body": "", "author_association": "NONE"},
            {"number": 6, "node_id": "F", "title": "[REPO] unknown", "state": "open", "body": ""},
        ]
        selected = project_sync.select_canonical_issues(issues, {"B": object()})
        self.assertEqual([i["number"] for i in selected], [1, 2])

    def test_bootstrap_derived_control_uses_shared_canonical_control_lookup(self):
        calls = []

        class FakeControlTrust:
            def get_repository_control(self, repository):
                calls.append(repository)
                return {"repository": repository, "issue_number": 7}

        canonical = {
            "number": 7,
            "node_id": "BOT-CONTROL",
            "title": "[REPO] demo",
            "state": "open",
            "body": "## Repository\n\nkinoko34077/demo",
            "author_association": "NONE",
        }
        collision = {**canonical, "number": 8, "node_id": "BOT-COLLISION"}

        self.assertTrue(
            project_sync.is_trusted_sync_issue(
                canonical,
                control_trust_service=FakeControlTrust(),
            )
        )
        self.assertFalse(
            project_sync.is_trusted_sync_issue(
                collision,
                control_trust_service=FakeControlTrust(),
            )
        )
        self.assertEqual(calls, ["kinoko34077/demo", "kinoko34077/demo"])

    def test_untrusted_non_control_never_uses_derived_control_trust(self):
        class MustNotRun:
            def get_repository_control(self, repository):
                raise AssertionError("non-Control bot Issue must not use derived Control trust")

        issue = {
            "number": 8,
            "title": "[WORK ORDER] spoof",
            "state": "open",
            "author_association": "NONE",
        }
        self.assertFalse(
            project_sync.is_trusted_sync_issue(
                issue,
                control_trust_service=MustNotRun(),
            )
        )

    def test_direct_trusted_non_control_preserves_existing_author_boundary(self):
        class MustNotRun:
            def get_repository_control(self, repository):
                raise AssertionError("direct trusted non-Control must not use Control verifier")

        issue = {
            "number": 9,
            "title": "[WORK ORDER] accepted",
            "state": "open",
            "author_association": "OWNER",
        }
        self.assertTrue(
            project_sync.is_trusted_sync_issue(
                issue,
                control_trust_service=MustNotRun(),
            )
        )

    def test_full_selection_can_include_derived_control_without_allowing_bot_work_order(self):
        class FakeControlTrust:
            def get_repository_control(self, repository):
                return {"repository": repository, "issue_number": 7}

        issues = [
            {
                "number": 7,
                "node_id": "BOT-CONTROL",
                "title": "[REPO] demo",
                "state": "open",
                "body": "## Repository\n\nkinoko34077/demo",
                "author_association": "NONE",
            },
            {
                "number": 8,
                "node_id": "BOT-WO",
                "title": "[WORK ORDER] spoof",
                "state": "open",
                "body": "",
                "author_association": "NONE",
            },
        ]
        selected = project_sync.select_canonical_issues(
            issues,
            {},
            control_trust_service=FakeControlTrust(),
        )
        self.assertEqual([issue["number"] for issue in selected], [7])

    def test_targeted_and_post_write_reads_accept_only_shared_canonical_control(self):
        canonical = {
            "number": 7,
            "node_id": "BOT-CONTROL",
            "title": "[REPO] demo",
            "state": "open",
            "body": "## Repository\n\nkinoko34077/demo",
            "author_association": "NONE",
        }

        class FakeREST:
            def get_issue(self, number):
                return dict(canonical)

        class FakeControlTrust:
            def get_repository_control(self, repository):
                return {"repository": repository, "issue_number": 7}

        rest = FakeREST()
        service = FakeControlTrust()
        self.assertEqual(
            project_sync.select_target_issue(
                rest,
                7,
                control_trust_service=service,
            )[0]["number"],
            7,
        )
        self.assertEqual(
            project_sync.reread_event_issue(
                rest,
                canonical,
                control_trust_service=service,
            )["number"],
            7,
        )

    def test_event_sync_ignores_untrusted_issue_without_project_access(self):
        class NoAccess:
            def __getattr__(self, name):
                raise AssertionError(f"untrusted event must not touch Project/REST: {name}")

        cfg = project_sync.RuntimeConfig(repository="kinoko34077/devflow", project_token="token", github_token="token")
        issue = {"number": 7, "node_id": "G", "title": "[REPO] spoof", "state": "open", "body": "", "author_association": "NONE"}
        self.assertEqual(project_sync.run_sync("event-sync", cfg, rest=NoAccess(), gql=NoAccess(), event_issue=issue), 0)

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
                return [
                    {"id": name, "name": name, "kind": "date" if name in project_sync.DATE_FIELDS else "text", "options": []}
                    for name in project_sync.EXPECTED_FIELDS
                ]
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
                    elif name in project_sync.DATE_FIELDS:
                        out.append({"id": name, "name": name, "kind": "date", "options": []})
                    else:
                        out.append({"id": name, "name": name, "kind": "text", "options": []})
                return out
            def get_project_items(self, project_id): return []
        with self.assertRaises(project_sync.ConfigError):
            project_sync.discover_project(FakeGraphQL(), project_sync.PROJECT_OWNER, project_sync.PROJECT_NUMBER)


class AuditProvenanceTests(unittest.TestCase):
    def test_audit_provenance_sections_map_to_existing_project(self):
        self.assertEqual(project_sync.FIELD_MAP["Audit Ref"], "Audit Ref")
        self.assertEqual(project_sync.FIELD_MAP["Last Audit At"], "Last Audit")
        self.assertEqual(project_sync.FIELD_MAP["Audit Depth"], "Audit Depth")
        self.assertEqual(project_sync.FIELD_MAP["Audit Scope"], "Audit Scope")
        self.assertEqual(project_sync.FIELD_MAP["Audit Evidence"], "Audit Evidence")
        self.assertEqual(project_sync.FIELD_MAP["Last Deep Audit At"], "Last Deep Audit")
        self.assertEqual(project_sync.SELECT_OPTIONS["Audit Depth"], {"CONTROL", "STANDARD", "DEEP"})
        self.assertEqual(project_sync.SELECT_OPTIONS["Audit Freshness"], {"CURRENT", "DRIFTED", "UNKNOWN"})

    def test_audit_freshness_uses_explicit_non_default_ref(self):
        calls = []
        issue = {
            "body": (
                "## Repository\n\n`kinoko34077/dev_agent`\n\n"
                "## Audit SHA\n\n`aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`\n\n"
                "## Audit Ref\n\n`v2/bootstrap`"
            )
        }
        def resolve(repository, ref):
            calls.append((repository, ref))
            return "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        self.assertEqual(project_sync.derive_audit_freshness(issue, resolve), "CURRENT")
        self.assertEqual(calls, [("kinoko34077/dev_agent", "v2/bootstrap")])

    def test_audit_freshness_unknown_without_ref_and_does_not_guess_default(self):
        calls = []
        issue = {
            "body": (
                "## Repository\n\n`kinoko34077/demo`\n\n"
                "## Audit SHA\n\n`aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`"
            )
        }
        def resolve(repository, ref):
            calls.append((repository, ref))
            return "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        self.assertEqual(project_sync.derive_audit_freshness(issue, resolve), "UNKNOWN")
        self.assertEqual(calls, [])

    def test_audit_freshness_reports_drift(self):
        issue = {
            "body": (
                "## Repository\n\n`kinoko34077/demo`\n\n"
                "## Audit SHA\n\n`aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`\n\n"
                "## Audit Ref\n\n`main`"
            )
        }
        self.assertEqual(
            project_sync.derive_audit_freshness(
                issue,
                lambda repository, ref: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            ),
            "DRIFTED",
        )

    def test_runtime_config_reads_maintenance_audit_token(self):
        cfg = project_sync.RuntimeConfig.from_env({
            "GITHUB_REPOSITORY": "kinoko34077/devflow",
            "PROJECTS_TOKEN": "project",
            "GITHUB_TOKEN": "repo",
            "MAINTENANCE_AUDIT_TOKEN": "audit",
        })
        self.assertEqual(cfg.maintenance_audit_token, "audit")

    def test_reconcile_can_create_only_missing_audit_project_fields(self):
        class FakeGraphQL:
            def __init__(self):
                self.created = []
            def get_project_identity(self, owner, number):
                return {"id": "P", "title": project_sync.PROJECT_TITLE, "public": False}
            def get_project_fields(self, project_id):
                return [
                    {"id": "existing", "name": "Audit SHA", "kind": "text", "options": []},
                ]
            def create_project_field(self, project_id, name, kind, options):
                self.created.append((project_id, name, kind, options))
        gql = FakeGraphQL()
        project_sync.ensure_audit_project_fields(gql, project_sync.PROJECT_OWNER, project_sync.PROJECT_NUMBER)
        created_names = {row[1] for row in gql.created}
        self.assertEqual(created_names, set(project_sync.AUDIT_PROJECT_FIELD_SPECS))
        self.assertNotIn("Audit SHA", created_names)

    def test_audit_timestamp_projects_to_date_without_losing_control_timestamp(self):
        issue = {
            "state": "open",
            "body": (
                "## Last Audit At\n\n`2026-10-01T08:15:44Z`\n\n"
                "## Last Deep Audit At\n\n`2026-09-30T23:59:59+00:00`"
            ),
        }
        fields = project_sync.desired_project_fields(issue)
        self.assertEqual(fields["Last Audit"], "2026-10-01")
        self.assertEqual(fields["Last Deep Audit"], "2026-09-30")

    def test_process_projects_freshness_without_mutating_control_audit_sha(self):
        issue = {
            "node_id": "ISSUE",
            "number": 9,
            "state": "open",
            "body": (
                "## Repository\n\n`kinoko34077/demo`\n\n"
                "## Audit SHA\n\n`aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`\n\n"
                "## Audit Ref\n\n`main`\n\n"
                "## Last Audit At\n\n`2026-10-01T08:15:44Z`\n\n"
                "## Audit Depth\n\n`CONTROL`"
            ),
        }
        fields = {
            "Managed Repository": project_sync.ProjectField("REPO", "Managed Repository", "text", {}),
            "Audit SHA": project_sync.ProjectField("SHA", "Audit SHA", "text", {}),
            "Audit Ref": project_sync.ProjectField("REF", "Audit Ref", "text", {}),
            "Last Audit": project_sync.ProjectField("LAST", "Last Audit", "date", {}),
            "Audit Depth": project_sync.ProjectField("DEPTH", "Audit Depth", "single", {"CONTROL": "C"}),
            "Audit Freshness": project_sync.ProjectField("FRESH", "Audit Freshness", "single", {"CURRENT": "CUR"}),
        }
        current = {
            "Managed Repository": "kinoko34077/demo",
            "Audit SHA": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "Audit Ref": "main",
            "Last Audit": "2026-10-01",
            "Audit Depth": "CONTROL",
            "Audit Freshness": "CURRENT",
        }
        snap = project_sync.ProjectSnapshot(
            "P", project_sync.PROJECT_TITLE, False, fields,
            {"ISSUE": project_sync.ProjectItem("I", "ISSUE", 9, "kinoko34077/devflow", current)},
        )
        class NoWrite:
            def __getattr__(self, name):
                raise AssertionError(name)
        summary = project_sync.process_issues(
            [issue], snap, NoWrite(), "verify",
            freshness_resolver=lambda repository, ref: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )
        self.assertEqual(summary["drift_fields"], 0)
        self.assertEqual(summary["errors"], [])
    def test_project_workflow_supplies_read_token_for_freshness(self):
        path = Path(__file__).parents[1] / ".github" / "workflows" / "project-sync.yml"
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text.count("MAINTENANCE_AUDIT_TOKEN"), 4)


class AuditFreshnessLabelProjectionTests(unittest.TestCase):
    def test_projection_label_vocabulary_is_closed_and_machine_owned(self):
        self.assertEqual(
            project_sync.AUDIT_FRESHNESS_LABELS,
            {
                "CURRENT": "devflow:audit-freshness:current",
                "DRIFTED": "devflow:audit-freshness:drifted",
                "UNKNOWN": "devflow:audit-freshness:unknown",
            },
        )
        self.assertEqual(
            set(project_sync.AUDIT_FRESHNESS_LABEL_SPECS),
            set(project_sync.AUDIT_FRESHNESS_LABELS.values()),
        )

    def test_projection_plan_preserves_unrelated_labels_and_repairs_stale_value(self):
        issue = {
            "title": "[REPO] demo",
            "labels": [
                {"name": "keep-me"},
                {"name": "devflow:audit-freshness:current"},
            ],
        }
        plan = project_sync.plan_audit_freshness_label_projection(issue, "DRIFTED")
        self.assertEqual(plan.status, "DRIFT")
        self.assertEqual(plan.add, ("devflow:audit-freshness:drifted",))
        self.assertEqual(plan.remove, ("devflow:audit-freshness:current",))

    def test_projection_plan_is_match_only_for_exactly_one_desired_label(self):
        issue = {
            "title": "[REPO] demo",
            "labels": [
                {"name": "devflow:audit-freshness:current"},
                {"name": "keep-me"},
            ],
        }
        plan = project_sync.plan_audit_freshness_label_projection(issue, "CURRENT")
        self.assertEqual(plan.status, "MATCH")
        self.assertEqual(plan.add, ())
        self.assertEqual(plan.remove, ())

    def test_projection_plan_flags_missing_and_multiple_machine_labels(self):
        missing = {"title": "[REPO] demo", "labels": [{"name": "keep-me"}]}
        multiple = {
            "title": "[REPO] demo",
            "labels": [
                {"name": "devflow:audit-freshness:current"},
                {"name": "devflow:audit-freshness:unknown"},
            ],
        }
        self.assertEqual(
            project_sync.plan_audit_freshness_label_projection(missing, "UNKNOWN").status,
            "DRIFT",
        )
        plan = project_sync.plan_audit_freshness_label_projection(multiple, "DRIFTED")
        self.assertEqual(plan.status, "DRIFT")
        self.assertEqual(set(plan.remove), {
            "devflow:audit-freshness:current",
            "devflow:audit-freshness:unknown",
        })
        self.assertEqual(plan.add, ("devflow:audit-freshness:drifted",))

    def test_projection_is_not_applicable_to_non_control_issue(self):
        issue = {"title": "[WORK ORDER] x", "labels": []}
        plan = project_sync.plan_audit_freshness_label_projection(issue, "CURRENT")
        self.assertEqual(plan.status, "NOT_APPLICABLE")
        self.assertEqual(plan.add, ())
        self.assertEqual(plan.remove, ())

    def test_verify_projection_is_read_only_and_reports_drift(self):
        class NoWriteREST:
            def __getattr__(self, name):
                raise AssertionError(name)
        issue = {"number": 59, "title": "[REPO] demo", "labels": []}
        result = project_sync.sync_audit_freshness_label_projection(
            issue, "CURRENT", NoWriteREST(), "verify"
        )
        self.assertEqual(result["status"], "DRIFT")
        self.assertEqual(result["mutations"], 0)

    def test_reconcile_projection_removes_only_machine_labels_then_adds_desired(self):
        class FakeREST:
            def __init__(self):
                self.removed = []
                self.added = []
            def remove_issue_label(self, issue_number, label):
                self.removed.append((issue_number, label))
            def add_issue_labels(self, issue_number, labels):
                self.added.append((issue_number, tuple(labels)))
        rest = FakeREST()
        issue = {
            "number": 59,
            "title": "[REPO] demo",
            "labels": [
                {"name": "keep-me"},
                {"name": "devflow:audit-freshness:current"},
            ],
        }
        result = project_sync.sync_audit_freshness_label_projection(
            issue, "DRIFTED", rest, "reconcile"
        )
        self.assertEqual(rest.removed, [(59, "devflow:audit-freshness:current")])
        self.assertEqual(rest.added, [(59, ("devflow:audit-freshness:drifted",))])
        self.assertEqual(result["status"], "REPAIRED")
        self.assertEqual(result["mutations"], 2)

    def test_ensure_projection_labels_creates_only_missing_system_labels(self):
        class FakeREST:
            def __init__(self):
                self.created = []
            def list_labels(self):
                return [{"name": "keep-me"}, {"name": "devflow:audit-freshness:current"}]
            def create_label(self, name, color, description):
                self.created.append((name, color, description))
        rest = FakeREST()
        count = project_sync.ensure_audit_freshness_labels(rest)
        self.assertEqual(count, 2)
        self.assertEqual(
            {row[0] for row in rest.created},
            {
                "devflow:audit-freshness:drifted",
                "devflow:audit-freshness:unknown",
            },
        )

    def test_process_counts_projection_drift_without_second_freshness_algorithm(self):
        issue = {
            "node_id": "ISSUE",
            "number": 59,
            "title": "[REPO] demo",
            "state": "open",
            "labels": [],
            "body": (
                "## Repository\n\n`kinoko34077/demo`\n\n"
                "## Audit SHA\n\n`aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`\n\n"
                "## Audit Ref\n\n`main`"
            ),
        }
        fields = {
            "Managed Repository": project_sync.ProjectField("REPO", "Managed Repository", "text", {}),
            "Audit SHA": project_sync.ProjectField("SHA", "Audit SHA", "text", {}),
            "Audit Ref": project_sync.ProjectField("REF", "Audit Ref", "text", {}),
            "Audit Freshness": project_sync.ProjectField(
                "FRESH", "Audit Freshness", "single", {"CURRENT": "CUR"}
            ),
        }
        current = {
            "Managed Repository": "kinoko34077/demo",
            "Audit SHA": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "Audit Ref": "main",
            "Audit Freshness": "CURRENT",
        }
        snap = project_sync.ProjectSnapshot(
            "P", project_sync.PROJECT_TITLE, False, fields,
            {"ISSUE": project_sync.ProjectItem("I", "ISSUE", 59, "kinoko34077/devflow", current)},
        )
        class NoWrite:
            def __getattr__(self, name):
                raise AssertionError(name)
        summary = project_sync.process_issues(
            [issue],
            snap,
            NoWrite(),
            "verify",
            freshness_resolver=lambda repository, ref: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            rest=NoWrite(),
        )
        self.assertEqual(summary["drift_fields"], 1)
        self.assertEqual(summary["errors"], [])


class AuditFreshnessPostWriteVerificationTests(unittest.TestCase):
    def test_event_sync_post_write_readback_refetches_live_issue(self):
        live = {
            "number": 59,
            "title": "[REPO] demo",
            "author_association": "OWNER",
            "labels": [{"name": "devflow:audit-freshness:unknown"}],
        }
        class FakeREST:
            def __init__(self):
                self.calls = []
            def get_issue(self, number):
                self.calls.append(number)
                return live
        rest = FakeREST()
        event_issue = {
            "number": 59,
            "title": "[REPO] demo",
            "author_association": "OWNER",
            "labels": [{"name": "devflow:audit-freshness:current"}],
        }
        observed = project_sync.reread_event_issue(rest, event_issue)
        self.assertIs(observed, live)
        self.assertEqual(rest.calls, [59])

    def test_event_sync_post_write_readback_rejects_invalid_identity(self):
        class FakeREST:
            def get_issue(self, number):
                raise AssertionError("must not read invalid event identity")
        with self.assertRaises(project_sync.ConfigError):
            project_sync.reread_event_issue(FakeREST(), {"title": "[REPO] demo"})

    def test_health_drift_message_covers_project_and_derived_projection(self):
        snapshot = project_sync.ProjectSnapshot(
            "P", project_sync.PROJECT_TITLE, False, {}, {}
        )
        result, body = project_sync._summary_health(
            "verify",
            snapshot,
            {
                "errors": [],
                "membership_drift": 0,
                "drift_fields": 1,
                "canonical_issues": 1,
                "project_items": 1,
            },
            "run",
        )
        self.assertEqual(result, "FAIL")
        self.assertIn("Synchronized value drift: 1", body)
        self.assertNotIn("Project field drift:", body)


class HealthFailureMemoryTests(unittest.TestCase):
    def test_unrelated_event_success_does_not_clear_prior_issue_failure(self):
        state = {}
        state = project_sync.update_health_failure_state(
            state,
            mode="event-sync",
            issue_number=180,
            failed=True,
            run_url="run-a",
            message="invalid Work Status",
        )
        state = project_sync.update_health_failure_state(
            state,
            mode="event-sync",
            issue_number=181,
            failed=False,
            run_url="run-b",
            message="",
        )
        self.assertIn("180", state)
        self.assertNotIn("181", state)

        snapshot = project_sync.ProjectSnapshot(
            "P", project_sync.PROJECT_TITLE, False, {}, {}
        )
        result, body = project_sync._summary_health(
            "event-sync",
            snapshot,
            {
                "errors": [],
                "membership_drift": 0,
                "drift_fields": 0,
                "canonical_issues": 1,
                "project_items": 1,
            },
            "run-b",
            unresolved_failures=state,
        )
        self.assertEqual(result, "FAIL")
        self.assertIn("#180", body)
        self.assertNotIn("## Result\nPASS", body)

    def test_same_issue_success_clears_prior_issue_failure(self):
        state = project_sync.update_health_failure_state(
            {},
            mode="event-sync",
            issue_number=180,
            failed=True,
            run_url="run-a",
            message="invalid Work Status",
        )
        state = project_sync.update_health_failure_state(
            state,
            mode="event-sync",
            issue_number=180,
            failed=False,
            run_url="run-a-fixed",
            message="",
        )
        self.assertEqual(state, {})

    def test_full_verify_pass_clears_scoped_and_global_failure_memory(self):
        state = project_sync.update_health_failure_state(
            {},
            mode="event-sync",
            issue_number=180,
            failed=True,
            run_url="run-a",
            message="invalid Work Status",
        )
        state = project_sync.update_health_failure_state(
            state,
            mode="verify",
            issue_number=None,
            failed=True,
            run_url="full-fail",
            message="global configuration failure",
        )
        self.assertIn("180", state)
        self.assertIn("global", state)

        state = project_sync.update_health_failure_state(
            state,
            mode="verify",
            issue_number=None,
            failed=False,
            run_url="full-pass",
            message="",
        )
        self.assertEqual(state, {})

    def test_failure_memory_round_trips_in_health_body(self):
        state = {
            "180": {
                "mode": "event-sync",
                "run_url": "https://github.com/x/actions/runs/1",
                "message": "invalid Work Status",
            }
        }
        body = project_sync.render_health_report(
            result="FAIL",
            mode="event-sync",
            project={"owner": "kinoko34077", "number": 1, "title": project_sync.PROJECT_TITLE},
            coverage={"canonical_issues": 1, "project_items": 0, "drift_fields": 0, "errors": 1},
            messages=["invalid Work Status"],
            run_url="https://github.com/x/actions/runs/1",
            unresolved_failures=state,
        )
        self.assertEqual(project_sync.parse_health_failure_state(body), state)
        self.assertIn("Unresolved Scoped Failures", body)


if __name__ == "__main__":
    unittest.main()
