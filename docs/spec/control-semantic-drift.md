# Control semantic consistency: bounded evidence contract (devflow #726)

Status: **M1 bounded comparator accepted; M2 devflow-only native postmerge PR-stage and explicit owner-linked review pilots accepted on 2026-10-22**. Full multi-repository transition coverage, unlinked/undeclared PR relevance, M3 and M4 remain OPEN. No active Control authority, no repair bot, no replacement for Cursor #576 or SMC #588.

## What causes the defect?

The controlling worker can accept a scoped PR/Issue transition without changing the directly affected human-readable `Next Action` on a Repository Control. GitHub Project / Repo Monitor can then present a snapshot that is structurally trusted and current but **semantically wrong** about that one task. Conversely `Work Status=AUDITED` and an open implementation PR are often perfectly compatible, because audit status and a task's implementation state are separate dimensions.

Changing a single status label, comparing a historical Audit SHA to latest main, or counting open PRs does not establish semantic mismatch.

## Explicit evidence (M1)

`tools/control_semantic_drift.py::compare_claim` accepts **one source-verified current Control claim** and **one independently verified complete observed fact**, with the same repository, exact subject and dimension. Caller is responsible for obtaining real current GETs and for classifying the specific active `Next Action` / `Active Work` statement; historical text is not a current claim. The comparator does not parse arbitrary prose, access GitHub, update Issues or select an implementation owner.

- `PR_GATE`: OPEN, AWAIT_REVIEW, AWAIT_MERGE, MERGED, CLOSED_UNMERGED, UNKNOWN. OPEN is GitHub PR state, not review readiness.
- `PUBLIC_ENTRY`: UNVERIFIED, VERIFIED, FAILED, UNKNOWN. This is about an actual published entry, not just a Pages build.
- `FIELD_ACCEPTANCE`: UNVERIFIED, ACCEPTED, REJECTED, UNKNOWN. Physical usability or audio experience cannot be inferred from CI.
- `BILLING_PREFLIGHT_DEPLOYMENT`: CODE_ONLY, READ_ONLY_LIVE, ROUTING_LIVE, UNKNOWN. `CODE_ONLY` means merged model/adapter/test code without an independently observed deployed authenticated reader; `READ_ONLY_LIVE` requires a real current preflight GET/retained result but NO job routing; `ROUTING_LIVE` requires an effect-time trusted route decision and independently observed action. A GitHub Actions CI pass cannot establish the latter two.
- `PRIVATE_EXECUTOR_ADMISSION`: NOT_ADMITTED, ADMITTED, UNKNOWN. `ADMITTED` requires independently authenticated owner/host authorization and protected Private source/isolation/resource constraints, not simply a manual immutable Public WSL job or a green test suite. `NOT_ADMITTED` is an explicitly verified negative operational decision, **not** inferred merely from a missing deployment receipt.

The last two axes were added after actual #752 R1/R2 code-only vs runtime confusion and [#726 2026-10-21 findings](https://github.com/kinoko34077/devflow/issues/726#issuecomment-6316896155). They are comparison vocabulary ONLY, not runtime adapters. A current reader must independently acquire exact same-subject source facts and treat absence of evidence as UNKNOWN. `BILLING_PREFLIGHT_DEPLOYMENT` and `PRIVATE_EXECUTOR_ADMISSION` are intentionally different dimensions: a live billing GET does not grant access to a Private executor or native GitHub Checks.
- Each side supplies a GitHub source URL and its actual timezone-aware read timestamp. Control URL must be an exact devflow Issue; observed URL must identify the **same owning repository and Issue/PR number**, with a PR URL required for PR_GATE. The comparator rejects credentials, ports, query strings and unrelated paths. Those checks are necessary but **not proof** that a source was independently authenticated.
- For comparison, the observed read must be at or after the Control read and within one hour. Earlier or excessively separated reads return UNKNOWN rather than an ALIGNED/MISMATCH assertion. Actual event chronology/version authority requires upstream validation; timestamps by themselves cannot prove causality.
- `source_verified` / `source_complete` are caller-supplied assertions and **cannot themselves establish trusted provenance**. Only an authenticated, complete canonical GET adapter may populate them; do not feed the function ad hoc untrusted Issue text.
- Results: `ALIGNED`, `POTENTIAL_MISMATCH`, `NOT_COMPARABLE`, `UNKNOWN`. A potential mismatch is a **review candidate only**; no automatic correction, claim/permission change or read-to-write promotion. Incomplete, unverifiable, historical, mismatched or otherwise ambiguous evidence does not become a positive finding.

`UNVERIFIED` for FIELD_ACCEPTANCE or PUBLIC_ENTRY is an absence of recorded proof, **not a contradictory failure**; the comparator returns UNKNOWN unless both sides have affirmative, same-scope observations. The caller must still independently check stage/version equivalence and event chronology. The v1 comparator enforces read-order and freshness bounds but does not prove event causality, GitHub actor identity, review authenticity, actual public URL health or effective product acceptance. A field name or GitHub-shaped URL is not proof of verified provenance.

## M2 bounded native-read pilot（2026-10-22、単一Public PR限定）

M1 comparatorだけでは、入力が現実の認証済みsourceであることを証明できない。既存`tools/control_semantic_pilot.py`は、既存認証`gh api`を使いControl #705と`kinotch-editor-platform` PR #14の**2本の固定GET**を行い、CURRENT `## Next Action`にある単一のcanonical exact PR linkと明示stageを、実PRのidentity/base/head・取得順序と照合する。PRの`MERGED`／`CLOSED_UNMERGED`は実GitHub終端属性で判定する一方、`OPEN`だけでreview readinessは証明できない。曖昧な文面・複数claim・歴史節・認証/GET失敗・入力不一致は`UNKNOWN`。M1 `compare_claim`を再利用し、`POTENTIAL_MISMATCH`は候補であって自動修正指示ではない。

実行は承認済みCLI環境の`python -m tools.control_semantic_pilot`。URL・観測時刻・PR HEADのsanitized出力のみとし、token/Issue原文を公開しない。合成REST fixtureによる単体テストだけでlive GET成立と扱わない。

**当時の実証：** [PR #768](https://github.com/kinoko34077/devflow/pull/768)はmain `f7453ce4e018f8a834943c33fe31b3ab3df397a1`にmerge、exact-head Required [#39639341465](https://github.com/kinoko34077/devflow/actions/runs/39639341465) 2,093 PASS（14追加）、Formal Review #5603251343／Readiness [#39639341473 attempt2](https://github.com/kinoko34077/devflow/actions/runs/39639341473)／post-main Required [#39639606165](https://github.com/kinoko34077/devflow/actions/runs/39639606165)成功。既存認証のowner PCで、2026-10-21T17:00:16.629669ZのControl GETと17:00:19.125984ZのPR GETから`MERGED=MERGED/ALIGNED/exit0`を確認（PR HEAD `f6ef6f9980a80e5fbfa881db766f8231d2bb3e38`、一時ファイル清掃）。[受入証拠](https://github.com/kinoko34077/devflow/issues/726#issuecomment-6321748478)。

**受入境界：** この1 Public PRの認証付き観測であり、他Controlへの自然言語解析、常時検出、producer所有の更新防止、M3 projection、M4 fleet coverage、特権writer、schedulerや追加credentialを実装したものではない。拡張は別の正確な対象scope/parse契約と独立証拠を要する。

## Historical M0 observed cases (as of 2026-10-19; non-normative, not live current state)

| Control | Current claim to investigate | Owning source | M0 disposition |
| --- | --- | --- | --- |
| devflow #59 / Repo Monitor | PR #85 still awaiting review/merge | #84, merged PR #85 and PR #88 | Stale Next Action; Pages deployment succeeded later, direct external HTTP readback still unverified |
| devflow #714 / Site Kit | Pre-implementation evaluation is next | Site Kit #10, merged PR #30 | Stale instruction; M0 gate itself OPEN |
| devflow #705 / Editor Platform | Bootstrap note limits the Control's initial evidence scope | Editor #9, merged PR #10 | Scope disclaimer; not a proven stale claim |
| devflow #500 / Frequency Warp | Several stages coexist | Web #183, native #172 | No status mismatch established |
| devflow #23 / LINE | AUDITED plus open successor PR | #47, PR #67 | No status mismatch established |

## M2 producer-invoked exact PR stage check (2026-10-22; bounded)

Reuses `tools/control_semantic_pilot.py` (does not create a second comparator).
At an accepted transition, an authorized producer may explicitly run:

`python -m tools.control_semantic_pilot --control 705 --repository kinoko34077/kinotch-editor-platform --pr 15`

The checker performs exactly two bounded native `gh api GET` reads of the
selected Control and owning PR; it does not fetch source code, change a
permission, update an Issue, watch other repos, or schedule a daemon.
Only canonical exact subject links in the CURRENT `## Next Action` with
an explicit stage label are comparable. Current `OPEN` means only GitHub
`state=open`, not 'review accepted', mergeable or product-ready; it is
distinct from AWAIT_REVIEW and AWAIT_MERGE. Comparing OPEN with either pending-review stage returns UNKNOWN (different granularity), not a false mismatch. A later merged PR with an
unchanged explicit OPEN claim yields a POTENTIAL_MISMATCH review candidate,
never a Control auto-write. Missing/ambiguous claim or inconsistent source
yields UNKNOWN. The no-arguments #705/PR14 invocation remains supported.

Producer-owned affected-surface reconciliation under
`docs/operations/DURABLE_PROGRESS_EXTERNALIZATION.md` §7 remains the
authority. A producer must actually call and interpret this advisory
at their transition; merely merging this code does not install a hook.
Full automatic merge/Close interception and all-repository semantic
monitoring are NOT accepted by this bounded command.
### Opt-in producer-exit status gate

After an accepted PR transition, the producing worker can execute the same
scoped native reader with `--require-aligned`:

`python -m tools.control_semantic_pilot --control 705 --repository kinoko34077/kinotch-editor-platform --pr 15 --require-aligned`

Exit code **0** means exactly `ALIGNED` for the one scoped PR stage;
**2** means `POTENTIAL_MISMATCH` needing producer-owned recheck/repair;
**3** means `UNKNOWN`/`NOT_COMPARABLE` (missing source or inadequate
proof). JSON output is kept for durable receipts. Without the flag, the
established diagnostic command retains exit 0 for compatibility. A merge,
CI success or emitted JSON is not enough to close a bounded task if the
actual producer-exit check has never been called and the relevant Control
was not verified. This does **not** block GitHub merges: it only allows
an explicitly participating producer to refuse premature `DONE`.
It does not install a webhook, modify branch protection, update an Issue,
or make a scheduler. A strict UNKNOWN is a reason to inspect the affected
canonical surfaces, not permission to mark failure/complete.

## M2 devflow-only merged-PR event（単一Controlの実証）

`.github/workflows/control-semantic-postmerge.yml`は**devflow内のみ**の`pull_request.closed && merged=true`を受信し、既存read-only `tools/control_semantic_postmerge_event.py`→`check_pr_transition_once`→M1 `compare_claim`へ渡す。権限は`contents:read`／`issues:read`／`pull-requests:read`のみ。認証済みeventのrepo/PR identity、Control #16のcurrent `## Next Action`と**そのPRの正確なリンク・stage**を照合する。ControlもPRも書かず、検査候補とsanitized結果をrun summaryへ記録する。

- 実PRはMERGEDだがControlの対象claimがOPENなら`POTENTIAL_MISMATCH/exit2`、一致するMERGEDなら`ALIGNED/exit0`。
- 正確な現行対象PR link/言及がない場合は`NOT_APPLICABLE/exit0`（**不整合不存在の証明ではない**）。同番号の曖昧な言及、stage欠落/多義は`UNKNOWN/exit3`。別repo・壊れたevent identity・認証不能/情報不足はfail-closed `UNKNOWN`。
- 判定はmerge rollbackや自動Control更新ではなく、[#251](https://github.com/kinoko34077/devflow/issues/251)に沿い**producerが影響箇所を確認して修正・readbackする責務**。他repoのPR、未知の旧自然文、製品の公開/実機受入、fleet-wide event coverageは含まれない。

**実際の正負例：** [PR #776](https://github.com/kinoko34077/devflow/pull/776) merge `af280d0c9d6e23b31d31cdee949a030380240cf9`、Required [#39695059094](https://github.com/kinoko34077/devflow/actions/runs/39695059094) 2,132 PASS、post-main [#39695388127](https://github.com/kinoko34077/devflow/actions/runs/39695388127)成功。実自動[event #39695388458](https://github.com/kinoko34077/devflow/actions/runs/39695388458)がControl #16の古いPR #776 OPENをexit2で検出。ownerが該当stageをMERGEDへ修正後、同run再試行attempt2成功。[記録](https://github.com/kinoko34077/devflow/issues/726#issuecomment-6329124725)。一方docs [PR #777](https://github.com/kinoko34077/devflow/pull/777)の直接PR紐付けがない実[event #39696030967](https://github.com/kinoko34077/devflow/actions/runs/39696030967)は成功しても、`NOT_APPLICABLE`相当の限定負例であり`ALIGNED`と認定しない。一般化した自動修復・M3/M4受入は未達。

## M2 PR直結参照がない場合のowner-linked review（devflow限定）

PRをControl #16の現行Next Actionへ明示していなくても、既存Work Orderに関係するmergeはあり得る。`NOT_APPLICABLE`を不整合なしと誤解しないため、同じ`tools/control_semantic_postmerge_event.py`がPR templateの**1件の実効所有宣言**（`- Owning-Issue: #726`またはcanonical URL、従来の非bullet `Owning-Issue: URL`も対応）を解析する。

- 認証付きGETで**実merge PR・owning Issue・現在Controlのowner参照**が同一対象であることを確認できた場合にのみ、`RECONCILIATION_REVIEW_REQUIRED/exit4`。これは**関連を調べる義務の発見**であり、Controlの記述が誤りと確定したわけでもIssueのclose/自動修正の許可でもない。
- 宣言空欄は`NOT_APPLICABLE`（関連なしの保証ではない）、複数の実効宣言・不正・矛盾・GET不能/Identity不一致は`UNKNOWN/exit3`。コードフェンス内の例、引用、inline proseは所有欄・Close宣言ではない。`- Closes #N`は本当にmergeでIssueを終了させる場合に限り別の意味を持ち、単なる所有宣言の代用にはしない。
- producerは、実際の受入済み変更と対象ControlのNext Actionが対応するか再照合し、**必要がある箇所だけ**直す。単にこのfieldがあるという理由で、全PRをControlへ加える運用にはしない。別のparser/comparator/書込権限・token・runnerは追加しない。

**修正と実証：** 最初の[PR #778](https://github.com/kinoko34077/devflow/pull/778)に対する実自動[event #39706303305](https://github.com/kinoko34077/devflow/actions/runs/39706303305)は引用`Owning-Issue`を2番目の宣言と誤読してexit3であり、exit4の受入例ではない。[PR #780](https://github.com/kinoko34077/devflow/pull/780)が完全な行先頭の所有宣言（CRLF含む）のみを数えるよう修正。main `986884445b0e6f8fcbe6d24350200dd818d9b5ab`、2,137件のテスト・post-main [#39706669943](https://github.com/kinoko34077/devflow/actions/runs/39706669943)成功。実[event #39706669809](https://github.com/kinoko34077/devflow/actions/runs/39706669809)はPR #780の直接stageがない状態でもowner #726への言及からexit4となり、producerが関連するControl #16のPR #780 stageをMERGEDへ修正、attempt2成功。raw step-summary JSONは未取得であり、job exitとコードの対応以上は断定しない。[詳細](https://github.com/kinoko34077/devflow/issues/726#issuecomment-6330598972)。devflow限定の実証で、全repo/所有関係/自動修復の一般受入ではない。

## M2 owner omission coverage: existing GitHub PR closing keyword (bounded; pending actual live event)

The existing devflow PR template has two **distinct** fields:
`- Closes #` for an actually completed Issue and `- Owning-Issue:` for
ownership without completing the Issue. GitHub's closing keywords are
interpreted on default-branch PRs, with a relative `#N` resolving to
the caller repository and an explicit owner/repo-qualified reference
resolving to that repository; the target may already be CLOSED when
the post-merge workflow runs.

The already accepted `control_semantic_postmerge_event.py` reuses the
existing `_parse_owner_issue` resolver and authenticated Issue GET
for a *single populated* closing declaration when `Owning-Issue` is
empty. It recognizes all nine documented GitHub keyword forms:
`close`/`closes`/`closed`, `fix`/`fixes`/`fixed`, and
`resolve`/`resolves`/`resolved`. The keyword must begin its line (an
optional `- ` is accepted), followed by whitespace and one supported
Issue reference; the documented optional colon form is `Closes: #10`.
Keyword case is ignored. This reader deliberately does not parse
mid-sentence declarations, `*` or numbered list items, or commit-message
references, even where native GitHub may recognize them.
Trailing description text after that reference is allowed, including a
possessive suffix such as `Fix #726's post-merge reader`; a second Issue
reference remains ambiguous. This addresses source-level false negatives
where native GitHub closes an Issue but the bounded reader returned
`NOT_APPLICABLE` or `UNKNOWN`. See [GitHub's closing-keyword syntax](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue).
A verified related Issue, whether OPEN or already CLOSED due to the
merge, and an exact current corresponding Control owner mention yield
**only** `RECONCILIATION_REVIEW_REQUIRED` (exit 4), not an asserted
factual mismatch, automatic Issue Close or Control edit.

The blank `- Closes #` placeholder remains no evidence. Invalid,
ambiguous, contradictory, foreign-repo or non-default-branch closing
declarations return `UNKNOWN`. One populated owner field continues
to be honored; if both populated owner and closing references disagree,
treat that ambiguity as UNKNOWN rather than silently choosing one.
This remains a line-anchored, single-reference parser, not generic
natural-language Issue inference. It does not infer product acceptance,
fix 57 repository workflow coverage, or
automatically update a Control. Unit regressions prove the limited
parser contract. **Native merged PR event live proof remains a separate
acceptance gate**; never close a real owner Issue merely for a test.

### Required PR owner metadata gate (devflow PRs)

The Required `verify` job in `.github/workflows/project-sync-tests.yml`
validates the PR body on `opened`, `synchronize`, `reopened`, and
`edited`. A PR must declare one valid `Owning-Issue` reference or one
valid GitHub closing reference; when both are populated they must identify
the same Issue. Duplicate, malformed, fenced-only, inline-code, raw HTML
code-block, HTML-commented, missing, or contradictory declarations fail the
Required check. Literal HTML-comment markers in code spans are not interpreted
as comments and cannot hide a following rendered declaration.
Within raw HTML code regions, end-tag-like text in an HTML comment or a quoted
nested-tag attribute, and invalid end tags, do not terminate the region;
`<plaintext>` consumes the remainder of the PR body. An owner declaration
remains ignored until a valid matching close tag or the end of the body.
A closing declaration is accepted only
when the PR targets the repository's default branch, matching GitHub's
closing behavior.

This reuses the existing fenced-code and owner/closing parsers. It validates
the declared relation's syntax and consistency only; it does not fetch the
Issue or prove the reference exists. The post-merge reader keeps its separate
authenticated identity/state GET and retains `NOT_APPLICABLE` for historical
events with no declaration. That read result is not evidence that no owner
relation exists. The new Required gate does not update Issues or Controls and
does not change workflow permissions.

## Follow-on full M2 producer-owned prevention and M3–M4, not accomplished here

1. Add a **trusted, source-complete GET adapter** using existing devflow read transport/projection contracts; do not build a new privileged crawler or let the comparator infer reliability from JSON submitted by the caller.
2. Select accepted exact subject refs in owning task/PR transitions; producer-owned `affected-surface reconciliation` remains the first-line preventive action.
3. Offer a read-only, source-cited mismatch report showing uncertainty, observation time and the specific stale field. Normal stage difference must not be reported as drift.
4. Validate against a bounded real pilot, independent review, exact-head regression/CI, and independently re-read any later approved Control correction; do not mutate Controls based on this candidate alone.

Exit/rollback: delete this isolated comparator and tests if it gives false confidence or overlaps the existing M3 source; no runtime job, schedule, remote service or authorization state is changed.

## M2 immutable reusable source with a second Public caller — accepted one-repository live pilot

Cross-repository installation is NOT achieved by copying the devflow-only
postmerge workflow or by changing an author's free-form prose. The existing
`tools/control_semantic_postmerge_event.py` is parameterized with an exact
caller `kinoko34077/<repository>` and a verified devflow `[REPO]` Control
Issue number. The one-source parser and M1 comparator remain shared.

`.github/workflows/control-semantic-reusable.yml` is a public `workflow_call`
entrypoint. A separately approved **Public** caller must select an
immutable 40-character devflow `source_sha`, exact `control_issue`, and
invoke it from a local PR-closed/merged event. The called job validates
the caller's event repository/PR identity, checks out the selected devflow
source (not the caller's untrusted PR branch), and uses the caller's
read-only `GITHUB_TOKEN` to request exactly the specific public Control,
PR and explicitly marked owning Issue. Only read permissions are supplied.

An explicit canonical current Control PR stage yields the existing
`ALIGNED` or `POTENTIAL_MISMATCH` semantics. Without a PR link, one
template-compatible `- Owning-Issue: #N` or devflow Issue URL can yield
`RECONCILIATION_REVIEW_REQUIRED` **only** when a verified open owner
Issue is referenced by current Control Next Action; this is a review
candidate, never proof that a Control correction is required.
Missing owner/PR yields `NOT_APPLICABLE`, not full consistency; bad identity,
unavailable source and ambiguous data yield UNKNOWN. This cannot write
or close Issues, deploy, grant permissions or authorize a hosted Private
runner. Note: reusable workflow token permissions and hosted runner billing
belong to caller, so Private Actions #752 restrictions still apply.

**Verified distinct acceptance stages (2026-10-22):**
- [devflow PR #784](https://github.com/kinoko34077/devflow/pull/784)
  merged as `891db0cc774d352ec5067ad86cb187534b1409c9`, Required 2,158
  tests and postmain Required #39711460985 SUCCESS; formal review/readiness
  accepted. Initial extra comparator argument was fixed after failing CI.
- [2bit-cell-automaton PR #14](https://github.com/kinoko34077/2bit-cell-automaton/pull/14)
  merged as `a6d166fc1580d6866c0379f64a2cbf67ae3f7010`; caller source
  SHA exactly pinned to immutable devflow main. Target's PR and postmain
  Verify passed; application code was untouched.
- [Actual automatically triggered caller run #39711791438](https://github.com/kinoko34077/2bit-cell-automaton/actions/runs/39711791438)
  checked out shared devflow source and first job exited 4: the existing
  template owner marker `- Owning-Issue: #726` linked a relevant current
  Control #6 owner without a direct merged PR stage. This was a **review
  candidate**, not a confirmed contradiction. The producing worker verified
  merged PR and updated only Control #6's affected field. Same run attempt
  2 SUCCEEDED. No workflow-owned Issue mutation was performed.
- [Durable evidence on #726](https://github.com/kinoko34077/devflow/issues/726#issuecomment-6331292004).

### Owning-Issue repository namespace (2026-10-22 correction)

The immutable shared M2 reader must **not** assume a caller PR's unqualified
`- Owning-Issue: #N` refers to devflow. By GitHub's ordinary issue-reference
semantics, that form identifies `kinoko34077/<caller>#N`. In a devflow PR
it still means devflow, but in another repository it means the **caller-local**
Issue. Authors who intend a **devflow** owner from another repository must
write its full canonical URL:
`- Owning-Issue: https://github.com/kinoko34077/devflow/issues/726`.

An explicit canonical Issue URL may instead target the caller repository.
Only those two qualified namespaces are admitted; any third repository,
malformed or ambiguous reference, missing/closed Issue, incomplete
authenticated GET, or mismatched Issue identity yields `UNKNOWN`, never an
assumed devflow owner or automatic Control write. Caller-local `#N` must
also appear **qualified by caller repository** in the current devflow Control
Next Action (full caller URL or `caller-name#N`); a bare `#N` in that
devflow Control is a devflow Issue and does not match a caller-local owner.
For devflow owners, explicit devflow URL/`devflow#N` or bare `#N` in
the devflow Control can match.

This is a correctness fix for **future shared-source SHA revisions only**.
Historical 2bit-cell-automaton #14 used `- Owning-Issue: #726` intending
devflow: its existing reusable workflow is immutable-pinned to the prior
code, and its observed successful pilot remains dated evidence, **not**
proof that the relative owner syntax was safe. Do not revise a protected
caller or make a new hosted run merely to retroactively reinterpret history.
Any new caller needs explicit owner namespace and separate live acceptance.

**Unaccepted:** no guarantee when author omits or misidentifies the owner
field, no general relevance proof from an issue reference alone, no
57-repository distribution or Issue Close coverage, no Private hosted
runner assumption, no auto Control writer, and no M3/M4 program completion.
Every further caller must clear its own rules, protected workflows,
billing and independent real runtime acceptance.
