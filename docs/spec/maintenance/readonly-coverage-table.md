# SMC multi-angle coverage table — 3-PILOT read-only operator preview

Owner: [devflow #588](https://github.com/kinoko34077/devflow/issues/588), M7 derived view.
Status: **PREVIEW / no Project or Repo Monitor publication / no new rollout**.

## Purpose

The reader lists the currently enabled maintenance Lens slots and depths,
rather than treating a repository-wide Audit SHA, historical DEEP label or
closed Issue as proof that every requirement was checked. Historical v1
records lack immutable scope and must stay unbound; v2 attestation only
confirms scoped metadata identity, not independently completed verification.

## Native command (explicit accepted PILOT selection only)

Run in an existing **authorized local or CI read-only environment** with a
preconfigured `GITHUB_TOKEN` that has access to the selected repositories.

```bash
python scripts/maintenance_coverage_report.py \
  --repo-ledger 'kinoko34077/devflow#367' \
  --repo-ledger 'kinoko34077/execution-coordinator#127' \
  --repo-ledger 'kinoko34077/kinotch-repository-base#50' \
  --format markdown --output smc-coverage.md
```

For a machine-readable derived report use `--format json`. The script
does not POST, PATCH, PUT, dispatch Actions, create PRs, claim tasks or change
a Project. It refuses any repository outside those three accepted PILOTs and
requires each explicit repository/standing Ledger pair. Output is **local**;
do not publish a private repo inventory or token-bearing information.

## Fail-closed interpretation

- `NOT_RUN`: no trusted completed audit evidence for that slot/depth.
- `NO_COVERAGE`: incomplete or blocked latest record; not executed credit.
- `LEGACY_SCOPE_UNBOUND`: v1 historical substantive result but its actual
  immutable scope is missing; **not** a current-scope pass.
- `ATTESTED_SCOPE_MATCH`: v2 Lens, scope, canonical catalog digest and
  reproducible code source fingerprint agree, but actual test/inspection
  evidence remains a separate verification gate.
- `UNKNOWN_FINGERPRINT`, `SOURCE_DRIFT`, `CATALOG_DRIFT`,
  `LENS_DRIFT`, `SCOPE_DRIFT`, `AMBIGUOUS_HISTORY`, `UNTRUSTED` or
  `INSUFFICIENT_EVIDENCE`: must not be rendered as green or complete.
- External/FAST-dependent slots have no fingerprint without explicit,
  independently verified external observation; this preview supplies none.

The CLI performs native GET-only source reads before and after the Ledger
collector and requires stable exact code HEAD, baseline and repo catalog
blob IDs and digest. Changed or inaccessible sources abort the report
instead of using a stale or partial favorable matrix.

## Future acceptance gaps

M5 live owner-run publication→claim/ack→audit→complete is still **HOLD** with
no current legitimate supply on #209; do not synthesize tasks just to show
green. M6 onboarding of the remaining managed repos is separate and not
automatically authorized. M7 GitHub Project / Repo Monitor graphical
integration and physical mobile readability are not implemented by this CLI;
new write/projection authority and real observed pilot results must be
reviewed independently. M8 full fleet acceptance remains unproven.
