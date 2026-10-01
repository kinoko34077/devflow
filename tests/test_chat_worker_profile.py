import unittest
from datetime import datetime, timezone

from tools import chat_worker_bootstrap as contract
from tools import chat_worker_profile as profile


NOW = datetime(2026, 9, 28, 16, 0, tzinfo=timezone.utc)


def observation(system="claude", **overrides):
    probes = {name: False for name in profile.PROBES}
    probes.update(
        {
            "exec.python3": True,
            "exec.unittest": True,
            "os.linux": True,
            "surface.github_read": True,
            "surface.github_write": True,
            "surface.coordinator_claim": True,
        }
    )
    data = {
        "schema_version": profile.OBSERVATION_SCHEMA,
        "worker_system": system,
        "worker_session_id": f"{system}-20260928T155500Z-a1b2c3",
        "cycle": 1,
        "observed_at": "2026-09-28T15:55:00Z",
        "probes": probes,
    }
    data.update(overrides)
    return data


def build(obs, **kw):
    return profile.build_request(
        obs,
        target_repository=kw.get("target", "kinoko34077/execution-coordinator"),
        work_intent=kw.get("intent", "このリポ側に合わせてなんか作業して"),
        now=kw.get("now", NOW),
    )


class ProfileTests(unittest.TestCase):
    def test_builds_valid_phase_a_request_from_passed_probes_only(self):
        request = build(observation())
        contract.normalize_request(request)
        self.assertEqual(["python", "tests"], request["capabilities"])
        self.assertEqual(["linux"], request["environment"])
        self.assertEqual(["coordinator:claim", "github:read", "github:write"], request["tool_surfaces"])
        self.assertEqual("claude-20260928T155500Z-a1b2c3:c1", request["execution_attempt_id"])

    def test_same_observation_is_reproducible(self):
        self.assertEqual(build(observation()), build(observation()))

    def test_review_provenance_is_explicit_and_not_inferred_from_provider(self):
        plain = build(observation("claude"))
        self.assertNotIn("review_provenance", plain)

        obs = observation(
            "claude",
            review_provenance={
                "system": "  Claude   Code ",
                "model": " Claude Sonnet 5 ",
            },
        )
        request = build(obs)
        self.assertEqual(
            {"system": "Claude Code", "model": "Claude Sonnet 5"},
            request["review_provenance"],
        )
        self.assertEqual("claude", request["worker_system"])

    def test_provider_name_alone_grants_nothing(self):
        for system in contract.WORKER_SYSTEMS:
            with self.subTest(system=system):
                obs = observation(system, probes={name: False for name in profile.PROBES})
                request = build(obs)
                self.assertEqual([], request["capabilities"])
                self.assertEqual([], request["environment"])
                self.assertEqual([], request["tool_surfaces"])

    def test_identical_probes_give_identical_tags_across_providers(self):
        results = {
            system: {k: v for k, v in build(observation(system)).items() if k in ("capabilities", "environment", "tool_surfaces")}
            for system in contract.WORKER_SYSTEMS
        }
        self.assertEqual(1, len({repr(value) for value in results.values()}))

    def test_fail_closed_observations(self):
        cases = {
            "unknown schema": observation(schema_version="chat-worker-observation.v2"),
            "unknown field": dict(observation(), token="x"),
            "unknown probe": observation(probes={**observation()["probes"], "exec.rust": True}),
            "missing checklist probe": observation(probes={"exec.python3": True}),
            "non-boolean probe": observation(probes={**observation()["probes"], "exec.git": "yes"}),
            "session belongs to other system": observation("codex", worker_session_id="claude-20260928T155500Z-a1b2c3"),
            "secret-shaped session id": observation(worker_session_id="ghp_abcdefabcdef"),
            "stale observation": observation(observed_at="2026-09-28T14:00:00Z"),
            "future observation": observation(observed_at="2026-09-28T16:30:00Z"),
            "bad cycle": observation(cycle=0),
            "two operating systems": observation(probes={**observation()["probes"], "os.windows": True}),
        }
        for label, obs in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(profile.ProfileError):
                    build(obs)

    def test_invalid_target_repository_fails_closed(self):
        with self.assertRaises(profile.ProfileError):
            build(observation(), target="not-a-repo")

    def test_session_and_attempt_identity_rules(self):
        session = profile.new_session_id("codex", datetime(2026, 9, 28, 15, 55, tzinfo=timezone.utc), "0f0f0f")
        self.assertEqual("codex-20260928T155500Z-0f0f0f", session)
        self.assertEqual(f"{session}:c3", profile.attempt_id(session, 3))
        with self.assertRaises(profile.ProfileError):
            profile.new_session_id("codex", datetime(2026, 9, 28, 15, 55), "0f0f0f")
        with self.assertRaises(profile.ProfileError):
            profile.new_session_id("gemini", datetime(2026, 9, 28, 15, 55, tzinfo=timezone.utc), "0f0f0f")

    def test_profile_drives_capability_matching_end_to_end(self):
        # A chat without a shell reports exec probes false and is therefore
        # omitted from python-requiring work by the Phase A classifier.
        import json
        from pathlib import Path

        example = json.loads(
            (Path(__file__).resolve().parents[1] / "docs/spec/examples/chat-worker-bootstrap/01-broad-instruction-fresh-claim.json").read_text(encoding="utf-8")
        )
        probes = {name: False for name in profile.PROBES}
        probes.update({"os.linux": True, "surface.github_read": True, "surface.github_write": True, "surface.coordinator_claim": True})
        obs = observation("chatgpt", probes=probes, observed_at="2026-09-28T14:58:00Z")
        request = build(obs, now=datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc))
        self.assertEqual(example["request"]["observed_at"], request["observed_at"])
        result = contract.classify(request, example["evidence"])
        self.assertEqual("NO_ELIGIBLE_WORK", result["disposition"])
        self.assertEqual("CAPABILITY_MISMATCH", result["omissions"][0]["reason"])

    def test_provider_checklists_cover_every_probe(self):
        for system in contract.WORKER_SYSTEMS:
            self.assertEqual(sorted(profile.PROBES), sorted(profile.PROVIDER_CHECKLISTS[system]))


if __name__ == "__main__":
    unittest.main()
