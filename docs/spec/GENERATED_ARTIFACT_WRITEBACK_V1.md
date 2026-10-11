# 検証済み生成物の書戻し v1 — 契約と受入証拠（S5更新候補）

**文書状態:** S3.6単一リポジトリPilotの実環境証拠を記録したDraft。**親devflow #384のS3 Exit・S4・S5正式受入は、JO Caller #308の統合後main CIを含む最終ゲート確認まで未確定**。本書だけで受入・横展開の承認とはしない。  
**正本:** [devflow #384](https://github.com/kinoko34077/devflow/issues/384)、[devflow #415](https://github.com/kinoko34077/devflow/issues/415)、[JO #300](https://github.com/kinoko34077/japanese-orthography/issues/300)。  
**実装の受入済み固定SHA:** `f886877e7110f2499125ecc6e07294798c33fe93`（[devflow PR #417](https://github.com/kinoko34077/devflow/pull/417)）。現mainが先に進んでもCaller pinを自動更新しない。

## S3.6の実環境証拠とv1受入の範囲

- **対象:** `kinoko34077/japanese-orthography` 1 repository、recipe `jo-orthography-accounting@1`、path `data/reports/orthography-v2-source-accounting.json` 1ファイル、専用`artifact/devflow384/` prefixのopen同一repository PR branchのみ。main/default branch、他path/recipe/repo、fork、保護branch/rulesets対象は許可しない。
- **起動と権限:** 承認済みdefault branchの`workflow_dispatch`からreview済みSHAを固定したreusable workflowのみ実行。生成jobは`contents:read`のみ、secretなし。別のwriter jobだけ`contents:write`・`actions:read`・`pull-requests:read`。writerは対象repoソースやZIPのコードをcheckout/実行せず、ZIP・manifestを低信頼データとして認証・検証する。権限やsecret/リポジトリ設定の恒久拡大はしていない。
- **認証と安全更新:** run/attempt/actor/workflow SHAとCaller pinのGitHub REST証拠を独立照合。manifest/ZIPのdigest、path・mode・容量等を検査。expected HEADのCAS、コミット単一親、`force:false`、実refの事後readbackを必須とする。証明できない更新結果や競合はfail-closed、勝手に再試行しない。
- **実writeと同一receipt replay:** [JO Run #38072681245](https://github.com/kinoko34077/japanese-orthography/actions/runs/38072681245)、attempt1で初回`COMMITTED`→同じreceiptの`NO_OP_REPLAY`、2回目Git変更0。writer commit `87557afe9d3585252c94cf5352515943323dd708`、parent `6d60b2c3669ba716a96c2111a3956d6cc7a7149e`、変更は許可JSONの末尾改行1個だけ。
- **正式な書込HEAD検証:** [JO Verify #38078533001](https://github.com/kinoko34077/japanese-orthography/actions/runs/38078533001)のread-only`pilot-head` Ubuntu/Windows両jobがwriter commit `87557afe...`を直接checkout、SHA一致検査と`npm run check`は両OS SUCCESS、Ubuntu`npm run build:site`もSUCCESS。run自体の`head_sha`は手動起動元mainのSHAであり、実検証対象はjob checkoutのSHAで判断する。PR仮想マージのCIと混同しない。
- **競合・負例:** [旧HEAD拒否 Run #37976552219](https://github.com/kinoko34077/japanese-orthography/actions/runs/37976552219) は意図した安全拒否（Actions全体のfailureを成功扱いしない）。[fresh NO_OP #37976192600](https://github.com/kinoko34077/japanese-orthography/actions/runs/37976192600)と同一receipt replayは別動作。devflow [postmain CI #38043365412](https://github.com/kinoko34077/devflow/actions/runs/38043365412)は862 tests＋compile SUCCESS、そのうちセキュリティ関連87 unit/static testsを含む。危険な攻撃payloadのlive特権実行を行ったという意味ではない。
- **復旧・試験後清掃:** writer SHAを親とする非強制rollback `ce4042b9868141f5b0736b1063a22a2748d721c5`で初期JSON blob `51d458e62770d8e5843dff5090458e84ef1d508f`へ復旧、専用[PR #304](https://github.com/kinoko34077/japanese-orthography/pull/304)は未統合Close。手動正確HEAD検証の一時入口は[PR #307](https://github.com/kinoko34077/japanese-orthography/pull/307)で旧Verify blobへ完全復元し、[JO postmain Verify #38113279718](https://github.com/kinoko34077/japanese-orthography/actions/runs/38113279718)は両OS SUCCESS。
- **残存する安全境界:** JO Callerの受入専用`write-replay-test`を除き、通常`dry-run/write`のみを許可する[PR #308](https://github.com/kinoko34077/japanese-orthography/pull/308)は独立レビュー＋PR-head両OS CI成功後に統合済み。job-level allowlistの意図しないmodeは`SKIPPED`として拒否し、機能成功と扱わない。最終mainの[postpush Verify #38116891632](https://github.com/kinoko34077/japanese-orthography/actions/runs/38116891632)の成功が正式S3 Exit前の残ゲート。
- **一般展開を明示的に除外:** devflow #386への横展開、任意ファイル/recipe、追加権限、release/deploy/Pages、JO TAR作業は本Pilot受入に含まれない。別の明示Human gateが必要。

---

## 以下はS2設計時点の歴史的契約（現在の実装状態ではない）

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
