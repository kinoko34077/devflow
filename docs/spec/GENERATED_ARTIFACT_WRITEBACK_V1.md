# Generated artifact verified writeback v1 — read-only contract candidate

Status: **S2 prototype / not an enabled writer**  
Owner: devflow#384  
Authority: devflow \`AGENTS.md\`, \`.devflow/WORKFLOW.yaml\`, #384  
Initial adoption: not enabled; S3 separately Human-gated single-repository PILOT.

## S3工程の現行提案とS2記述の区別（2026-10-09）

以下に記された「S2 prototype」「At this checkpoint only contract implemented」等の記述は、S2当時の歴史的スナップショットであり、**現在のS3コード・実Pilot受入状況を表すものではない**。

現行の開発対象はdevflow#384、統合security-review候補はDraft PR #392の `02a5d26202bb9d40dd534397128e6a5f068d4217`。GPTのwriterとClaudeのworkflowを最終状態へ積み重ねた段階であり、Required testsはGREENだが、統合全体の独立security Review、PR readiness、JO Pilot、merge/post-main/rollbackは未完了である。各PRの現在HEADと状態は常にliveで再取得する。

正式なphase-order変更**案**は `docs/operations/GENERATED_ARTIFACT_WRITEBACK_V1_RUNBOOK.md` の「§1A S3のtrusted SHA確立とPilot順序」を参照。未merge codeの権限付き実行は禁止という従来の安全境界は維持し、独立全体security ReviewとHumanによる前倒しbootstrap mergeの明示承認がない場合はS3出口をHOLDする。S3/S4の循環依存を解消する案の存在は、S3/S4/S5またはPilotの受入を意味しない。

## 1. Boundary

The purpose is to transfer large JSON/binary files from an unprivileged generator into a *separately privileged*, narrowly bounded GitHub PR-branch writer, without executing archive code and without ever authorizing arbitrary paths or push-to-main. Ordinary UTF-8 source file editing via existing GitHub Git Data / Contents API remains unchanged. Launch/discovery/claim/fencing from #202/#223/execution-coordinator is not part of this feature.

At this checkpoint **only** \`tools/generated_artifact_contract.py\` is implemented. It accepts **already authenticated** policy/admission/GitHub observations, an untrusted manifest and untrusted ZIP bytes and returns a read-only plan. No GitHub network calls, credentials, ref updates, Actions workflow or repository permission mutation exist in this prototype.

A successful dry-run is **not** the final permission to write.

## 2. Trusted inputs versus untrusted data

The trusted caller / eventual writer must supply policy and admission from a reviewed, pinned workflow/configuration plus authenticated GitHub context. It must observe branch HEAD and existing generated file bytes via trusted GitHub API before invoking the planner. Never infer trusted context from the ZIP or manifest. The producer's JSON is self-asserted low-trust data.

Policy shape (\`generated-artifacts-policy.v1\`):

\`\`\`json
{
  "schema": "generated-artifacts-policy.v1",
  "repository": "kinoko34077/example",
  "allowed_actors": ["kinoko34077"],
  "default_branch": "main",
  "branch_prefix": "artifact/",
  "forbidden_branches": ["master", "production"],
  "recipe": {
    "id": "canonical-json",
    "version": "1",
    "paths": ["dist/output.json", "dist/table.bin"]
  },
  "producer_workflow_ref": "kinoko34077/example/.github/workflows/generate.yml@ffffffffffffffffffffffffffffffffffffffff",
  "limits": {
    "max_files": 4,
    "max_file_bytes": 1000000,
    "max_total_bytes": 2000000,
    "max_archive_bytes": 3000000,
    "max_expansion_ratio": 500
  }
}
\`\`\`

Admission shape (not user-supplied command text; supplied by trusted caller after actor/run/source checks):

\`\`\`json
{
  "repository": "kinoko34077/example",
  "actor": "kinoko34077",
  "branch": "artifact/pilot-1",
  "expected_head": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "source_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "recipe_id": "canonical-json",
  "recipe_version": "1",
  "producer_run_id": 37752814325,
  "producer_run_attempt": 1,
  "producer_workflow_ref": "kinoko34077/example/.github/workflows/generate.yml@ffffffffffffffffffffffffffffffffffffffff"
}
\`\`\`

Manifest shape (\`generated-artifacts.v1\`):

\`\`\`json
{
  "schema": "generated-artifacts.v1",
  "provenance": { "...": "exact complete admission fields; untrusted until checked" },
  "files": [
    { "path": "dist/output.json", "size": 12, "sha256": "exact lowercase 64-hex SHA256" },
    { "path": "dist/table.bin", "size": 7, "sha256": "exact lowercase 64-hex SHA256" }
  ]
}
\`\`\`

Actual manifest entries contain the digest of each raw ZIP member. The ZIP must contain each expected path **exactly once** and no other entry. No files may be deleted or changed outside the allowlist. Binary members are checked byte-for-byte; executable extensions / dot paths are not admitted by default.

The caller must use **source SHA**, **producer workflow identity/SHA**, **run ID and attempt**, **actor** and **target head** as separately verified facts. The manifest cannot authenticate itself and a SHA256 digest does not establish producer trust.

## 3. S2 validation

\`validate_and_plan(policy, admission, manifest, archive_bytes, observed_head=..., existing_files=...)\`:
- rejects extra/missing keys, invalid identifiers, unsupported schema and unknown/unsafe file paths;
- requires an exact static recipe path set (not globbing), allowed actor/repository and branch prefix; rejects default/forbidden branch and stale head;
- rejects ZIP duplicate/extra/omitted entries, traversal, links/special files, encrypted members, member digest mismatch, byte ceilings, excessive expansion and malformed ZIP;
- reads members into bounded memory (limits have implementation ceilings); does not extract to filesystem, execute anything, install dependencies or write;
- compares allowlisted actual bytes to observed current bytes and returns a sorted \`CHANGE\` or \`NO_OP\` plan with manifest digest, file hashes, provenance/run and \`writes_performed: false\`.

Conservative S2 behavior: if target HEAD changed, reject even when generated files now match; idempotent **post-write** replay remains an S3 writer requirement with independently verified commit/provenance receipt. This avoids silently bypassing target-head fencing.

## 4. Remaining S3–S5 implementation contract (not yet authorized)

Future **read producer job**: fixed approved generator/recipe and tests, \`contents:read\`, no secrets/write token. Generate archive plus manifest. No free-form command input.

Future **trusted writer job**: explicitly gated \`contents:write\` in target repository's reviewed caller job; use SHA-pinned devflow shared implementation. No PR-source checkout/execute, \`npm install\`, \`pip install\`, or downloaded artifact scripts. Independently verify run identity, caller workflow ref, permissions, repository/actor, exact branch head, default/protected branches, archive digest/path-set and absence of unexpected modifications. Git Data API / non-force update must fail on concurrent move, with post-write readback. No default-branch writes or force push.

Future **idempotent retry**: reject stale expected head unless a verified earlier writeback receipt and exact target tree prove the **same** run/payload was already applied; then return a durable no-op. Different payload or unproven commit is conflict.

Future **CI**: \`GITHUB_TOKEN\` updates do not normally trigger new push CI. A trusted authorized path must explicitly start and verify the required tests for the **new exact head**; permissions such as \`actions:write\` are not implicitly granted. Separate independent Formal Review, guarded merge and post-main checks remain mandatory.

Future **pilot**: one separately owned repository and recipe with a dedicated scratch/PR branch; write, competing-head negative trial, duplicate retry, exact-head CI, rollback/revert trial and cleanup. No takeover of japanese-orthography#291/#210 or fleet-wide adoption.

**Human gate:** enabling the persistent target-repository caller/writer with \`contents:write\`, adding \`actions:write\` or authentication secrets/tokens, or changing Actions settings/rulesets/branch protection requires explicit scoped approval. S2 files do not constitute approval or deployment.

## 5. Test / evidence

\`python -W error -m unittest tests.test_generated_artifact_contract -v\`

The complete devflow Required PR gate independently runs \`python -W error -m unittest discover -v\` and Python compile check. An S2 successful test/PR is **not** S3 production or security acceptance. GitHub #384 Task Checkpoint Cursor/progress comments remain the recovery authority.

## 6. Failure handling

Reject all malformed/ambiguous inputs before plan output and before future writer effects. Never attempt to recover by widening a path set, using \`@main\` instead of a pinned workflow, force-moving a branch, or using a generic token from PR code. Human-gated settings remain unchanged on failure; leave the last accepted checkpoint and exact evidence on #384.
