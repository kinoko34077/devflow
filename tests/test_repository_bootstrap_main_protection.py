import copy
import unittest
import time
from unittest.mock import patch

from tools import repository_bootstrap as rb
from tests.test_repository_bootstrap import issue_body
from tests.test_repository_bootstrap_executor import FakeApi, context


FULL_NAME = "kinoko34077/example-repo"
POLICY = "public-only-v1"
BASELINE = {
    "required_status_checks": {
        "strict": False,
        "checks": [{"context": "verify", "app_id": 15368}],
    },
    "enforce_admins": True,
    "required_pull_request_reviews": {
        "required_approving_review_count": 0,
        "bypass_pull_request_allowances": {"users": [], "teams": [], "apps": []},
    },
    "required_conversation_resolution": True,
    "allow_force_pushes": False,
    "allow_deletions": False,
}
ORGANIZATION_BASELINE = {**BASELINE, "restrictions": None}


def request(visibility="public", *, with_policy=True):
    payload = rb.parse_request_body(issue_body())
    payload["repository"]["visibility"] = visibility
    if with_policy:
        payload["bootstrap"]["main_protection"] = POLICY
    return rb.normalize_request(payload, "[REPO CREATE] example-repo")


def protection_readback(baseline=BASELINE):
    """Shape returned by GET /branches/main/protection."""
    result = {
        "required_status_checks": {
            "strict": baseline["required_status_checks"]["strict"],
            "contexts": [item["context"] for item in baseline["required_status_checks"]["checks"]],
            "checks": copy.deepcopy(baseline["required_status_checks"]["checks"]),
        },
        "enforce_admins": {"enabled": baseline["enforce_admins"]},
        "required_pull_request_reviews": {
            **copy.deepcopy(baseline["required_pull_request_reviews"]),
        },
        "required_conversation_resolution": {
            "enabled": baseline["required_conversation_resolution"]
        },
        "allow_force_pushes": {"enabled": baseline["allow_force_pushes"]},
        "allow_deletions": {"enabled": baseline["allow_deletions"]},
    }
    if "restrictions" in baseline:
        result["restrictions"] = copy.deepcopy(baseline["restrictions"])
    return result


class ProtectionApi(FakeApi):
    def __init__(self):
        super().__init__()
        self.protections = {}
        self.protection_calls = []
        self.protection_payloads = []
        self.events = []
        self.fail_put_status = None
        self.fail_put_statuses = []
        self.fail_second_get_status = None
        self.owner_type = "User"

    def get_repository(self, full_name):
        repository = super().get_repository(full_name)
        if repository is None:
            return None
        repository = copy.deepcopy(repository)
        repository["owner"] = {"type": self.owner_type}
        return repository

    def create_file(self, full_name, path, content, message):
        self.events.append(("create_file", path))
        return super().create_file(full_name, path, content, message)

    def get_branch_protection(self, full_name, branch):
        self.protection_calls.append(("GET", full_name, branch))
        get_count = sum(call[0] == "GET" for call in self.protection_calls)
        if get_count == 2 and self.fail_second_get_status is not None:
            status = self.fail_second_get_status
            self.fail_second_get_status = None
            raise rb.GitHubApiError("GET protection failed", status_code=status)
        value = self.protections.get((full_name, branch))
        return copy.deepcopy(value)

    def set_branch_protection(self, full_name, branch, protection):
        self.events.append(("set_branch_protection", branch))
        self.protection_calls.append(("PUT", full_name, branch))
        self.protection_payloads.append(copy.deepcopy(protection))
        if self.fail_put_statuses:
            status = self.fail_put_statuses.pop(0)
            if status is not None:
                raise rb.GitHubApiError("PUT protection failed", status_code=status)
        if self.fail_put_status is not None:
            raise rb.GitHubApiError("PUT protection failed", status_code=self.fail_put_status)
        if self.owner_type == "User" and "restrictions" in protection:
            raise rb.GitHubApiError(
                "personal repositories do not accept push restrictions",
                status_code=422,
            )
        self.protections[(full_name, branch)] = protection_readback(protection)
        if self.owner_type == "User":
            self.protections[(full_name, branch)].pop("restrictions", None)
        return self.protections[(full_name, branch)]


class RepositoryBootstrapMainProtectionTests(unittest.TestCase):
    def test_public_bootstrap_applies_and_reads_back_the_accepted_baseline(self):
        repository, devflow = ProtectionApi(), FakeApi()

        rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        self.assertEqual("public", repository.repos[FULL_NAME]["visibility"])
        self.assertEqual("main", repository.get_default_branch_name(FULL_NAME))
        self.assertEqual("main", repository.protection_calls[0][2])
        self.assertEqual("PUT", repository.protection_calls[1][0])
        self.assertEqual("GET", repository.protection_calls[2][0])
        self.assertEqual([BASELINE], repository.protection_payloads)
        done = [body for _, _, body in devflow.comments if "State: DONE" in body]
        self.assertEqual(1, len(done))
        self.assertIn("Main-Protection: VERIFIED/PROTECTED", done[0])

    def test_public_bootstrap_seeds_read_only_verify_check_before_protection(self):
        repository, devflow = ProtectionApi(), FakeApi()

        rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        verify_path = ".github/workflows/verify.yml"
        workflow = repository.files[(FULL_NAME, verify_path)]
        self.assertIn("name: verify", workflow)
        self.assertIn("  push:\n    branches:\n      - main", workflow)
        self.assertIn("  pull_request:\n    branches:\n      - main", workflow)
        self.assertIn("jobs:\n  verify:", workflow)
        self.assertIn("permissions: {}", workflow)
        self.assertIn("      contents: read", workflow)
        self.assertIn("git fetch --no-tags --depth=1 origin \"$BASE_SHA\"", workflow)
        self.assertIn("if: github.event_name == 'pull_request'", workflow)
        self.assertIn("git diff --check \"$BASE_SHA\" \"$HEAD_SHA\"", workflow)
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("paths:", workflow)
        self.assertLess(
            repository.events.index(("create_file", verify_path)),
            repository.events.index(("set_branch_protection", "main")),
        )

    def test_new_verify_check_race_retries_protection_once_after_a_bounded_wait(self):
        repository, devflow = ProtectionApi(), FakeApi()
        repository.fail_put_statuses = [422, None]

        with patch.object(time, "sleep") as sleep:
            try:
                rb.BootstrapExecutor(repository, devflow).execute(request(), context())
            except rb.BootstrapFailure:
                succeeded = False
            else:
                succeeded = True

        self.assertTrue(succeeded, "a single transient 422 must retry after the check-availability wait")
        self.assertEqual(2, len(repository.protection_payloads))
        sleep.assert_called_once_with(15)

    def test_persistent_protection_validation_failure_stops_after_one_retry(self):
        repository, devflow = ProtectionApi(), FakeApi()
        repository.fail_put_status = 422

        with patch.object(time, "sleep") as sleep:
            with self.assertRaises(rb.BootstrapFailure) as caught:
                rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        self.assertEqual("MAIN_PROTECTION", caught.exception.stage)
        self.assertEqual("after-human-decision", caught.exception.safe_retry)
        self.assertEqual(2, len(repository.protection_payloads))
        sleep.assert_called_once_with(15)

    def test_public_bootstrap_records_head_after_all_seed_writes(self):
        repository, devflow = ProtectionApi(), FakeApi()

        result = rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        final_head = repository.get_default_branch_head(FULL_NAME)
        self.assertEqual(final_head, result.head_sha)
        controls = devflow.issues["kinoko34077/devflow"]
        self.assertEqual(1, len(controls))
        self.assertIn(final_head, controls[0]["body"])
        done = [body for _, _, body in devflow.comments if "State: DONE" in body]
        self.assertEqual(1, len(done))
        self.assertIn(f"Initial-Accepted-SHA: `{final_head}`", done[0])

    def test_matching_existing_protection_is_verified_without_rewriting(self):
        repository, devflow = ProtectionApi(), FakeApi()
        repository.protections[(FULL_NAME, "main")] = protection_readback()

        rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        self.assertEqual([("GET", FULL_NAME, "main")], repository.protection_calls)
        self.assertEqual([], repository.protection_payloads)

    def test_user_owned_public_repo_omits_unavailable_push_restrictions(self):
        repository, devflow = ProtectionApi(), FakeApi()

        rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        self.assertEqual("User", repository.get_repository(FULL_NAME)["owner"]["type"])
        self.assertNotIn("restrictions", repository.protection_payloads[0])
        self.assertNotIn("restrictions", repository.protections[(FULL_NAME, "main")])

    def test_organization_owned_public_repo_explicitly_disables_push_restrictions(self):
        repository, devflow = ProtectionApi(), FakeApi()
        repository.owner_type = "Organization"

        rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        self.assertIsNone(repository.protection_payloads[0]["restrictions"])
        self.assertIsNone(repository.protections[(FULL_NAME, "main")]["restrictions"])

    def test_organization_readback_requires_explicit_absence_of_push_restrictions(self):
        repository, devflow = ProtectionApi(), FakeApi()
        repository.owner_type = "Organization"
        repository.protections[(FULL_NAME, "main")] = protection_readback()

        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        self.assertEqual("MAIN_PROTECTION", caught.exception.stage)
        self.assertEqual([], repository.protection_payloads)

    def test_public_bootstrap_fails_closed_for_unknown_repository_owner_type(self):
        repository, devflow = ProtectionApi(), FakeApi()
        repository.owner_type = "Unknown"

        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        self.assertEqual("MAIN_PROTECTION", caught.exception.stage)
        self.assertEqual([], repository.protection_calls)

    def test_private_bootstrap_marks_protection_not_applicable_without_api_calls(self):
        repository, devflow = ProtectionApi(), FakeApi()

        rb.BootstrapExecutor(repository, devflow).execute(request("private"), context())

        self.assertEqual([], repository.protection_calls)
        self.assertNotIn((FULL_NAME, ".github/workflows/verify.yml"), repository.files)
        done = [body for _, _, body in devflow.comments if "State: DONE" in body]
        self.assertEqual(1, len(done))
        self.assertIn("Main-Protection: NOT_APPLICABLE/PRIVATE_REPOSITORY", done[0])

    def test_legacy_request_retry_does_not_gain_protection(self):
        repository, devflow = ProtectionApi(), FakeApi()

        rb.BootstrapExecutor(repository, devflow).execute(request(with_policy=False), context())

        self.assertEqual([], repository.protection_calls)
        done = [body for _, _, body in devflow.comments if "State: DONE" in body]
        self.assertEqual(1, len(done))
        self.assertIn("Main-Protection: NOT_APPLICABLE/LEGACY_V1_REQUEST", done[0])
        self.assertNotIn((FULL_NAME, ".github/workflows/verify.yml"), repository.files)

    def test_existing_conflicting_verify_workflow_fails_closed(self):
        repository, devflow = ProtectionApi(), FakeApi()
        repository.files[(FULL_NAME, ".github/workflows/verify.yml")] = "name: user workflow\n"

        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        self.assertEqual("SEED", caught.exception.stage)
        self.assertEqual([], repository.protection_payloads)
        self.assertEqual("name: user workflow\n", repository.files[(FULL_NAME, ".github/workflows/verify.yml")])

    def test_divergent_existing_policy_fails_closed_without_overwrite(self):
        repository, devflow = ProtectionApi(), FakeApi()
        divergent = protection_readback()
        divergent["allow_force_pushes"] = {"enabled": True}
        repository.protections[(FULL_NAME, "main")] = divergent

        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        self.assertEqual("MAIN_PROTECTION", caught.exception.stage)
        self.assertEqual([], repository.protection_payloads)
        self.assertTrue(any("Stage: MAIN_PROTECTION" in body for _, _, body in devflow.comments))

    def test_existing_push_restriction_is_divergent_and_is_not_overwritten(self):
        repository, devflow = ProtectionApi(), FakeApi()
        restricted = protection_readback()
        restricted["restrictions"] = {
            "users": ["automation-user"],
            "teams": [],
            "apps": [],
        }
        repository.protections[(FULL_NAME, "main")] = restricted

        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        self.assertEqual("MAIN_PROTECTION", caught.exception.stage)
        self.assertEqual([], repository.protection_payloads)

    def test_administration_permission_failure_stops_bootstrap_for_human_review(self):
        repository, devflow = ProtectionApi(), FakeApi()
        repository.fail_put_status = 403

        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        self.assertEqual("MAIN_PROTECTION", caught.exception.stage)
        self.assertEqual("after-human-decision", caught.exception.safe_retry)
        self.assertFalse(repository.issues.get(FULL_NAME))
        self.assertFalse(devflow.issues.get("kinoko34077/devflow"))

    def test_retry_after_put_succeeded_but_readback_failed_does_not_put_twice(self):
        repository, devflow = ProtectionApi(), FakeApi()
        repository.fail_second_get_status = 500
        executor = rb.BootstrapExecutor(repository, devflow)

        with self.assertRaises(rb.BootstrapFailure) as caught:
            executor.execute(request(), context())
        self.assertEqual("yes", caught.exception.safe_retry)
        self.assertEqual(1, len(repository.protection_payloads))

        executor.execute(request(), context())

        self.assertEqual(1, len(repository.protection_payloads))
        self.assertIn("main", [call[2] for call in repository.protection_calls])

    def test_public_policy_rejects_a_non_main_default_branch(self):
        repository, devflow = ProtectionApi(), FakeApi()
        original = repository.create_repository

        def create_with_trunk(owner, name, description, visibility):
            value = original(owner, name, description, visibility)
            value["default_branch"] = "trunk"
            repository.repos[value["full_name"]]["default_branch"] = "trunk"
            return value

        repository.create_repository = create_with_trunk

        with self.assertRaises(rb.BootstrapFailure) as caught:
            rb.BootstrapExecutor(repository, devflow).execute(request(), context())

        self.assertEqual("MAIN_PROTECTION", caught.exception.stage)
        self.assertEqual([], repository.protection_calls)

    def test_normalizer_accepts_policy_and_rejects_it_for_unmanaged_repository(self):
        payload = rb.parse_request_body(issue_body())
        payload["bootstrap"]["main_protection"] = POLICY
        self.assertEqual(POLICY, rb.normalize_request(payload, "[REPO CREATE] example-repo").main_protection)

        payload["bootstrap"]["devflow_managed"] = False
        payload["devflow"]["create_control"] = False
        with self.assertRaises(rb.BootstrapError):
            rb.normalize_request(payload, "[REPO CREATE] example-repo")

    def test_github_adapter_uses_narrow_branch_protection_endpoints(self):
        api = rb.GitHubApi("token")
        with patch.object(api, "_request", side_effect=[None, protection_readback()]) as call:
            self.assertIsNone(api.get_branch_protection(FULL_NAME, "feature/example"))
            api.set_branch_protection(FULL_NAME, "main", BASELINE)

        self.assertEqual("GET", call.call_args_list[0].args[0])
        self.assertIn("/branches/feature%2Fexample/protection", call.call_args_list[0].args[1])
        self.assertTrue(call.call_args_list[0].kwargs["allow_404"])
        self.assertEqual("PUT", call.call_args_list[1].args[0])
        self.assertIn("/branches/main/protection", call.call_args_list[1].args[1])
        self.assertEqual(BASELINE, call.call_args_list[1].args[2])
        self.assertNotIn("contexts", call.call_args_list[1].args[2]["required_status_checks"])


if __name__ == "__main__":
    unittest.main()

