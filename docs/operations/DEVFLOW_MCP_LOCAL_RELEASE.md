# Codex Devflow MCP — verified local release selector (#1111)

This procedure applies **only to the authorized KiNoTch. Windows Codex**
registration named `kinotch_devflow`. It is not a global repository bootstrap,
MCP protocol versioning scheme, Codex lifecycle fix or claim authority.

## Stable registration

Initial rollout [#1124](https://github.com/kinoko34077/devflow/issues/1124)
must use a protected Python runtime and source clone. If the existing registered
Python is writable by the development sandbox, the one-time, explicitly
authorized migration changes only the MCP Python `command` after a byte-for-byte
backup of `~/.codex/config.toml`. Preserve the three existing `args` (stable
launcher, authenticated `gh.exe`, immutable original `tools/devflow_mcp.py`),
registration environment and unrelated settings. Install
`tools/devflow_mcp_stable_launcher.py` **once**, after backing up the original
launcher. Routine release updates must not edit either registration or launcher.
The old third argument remains the fallback.

A local read-only state file determines which *newly started* server is selected:

```text
%LOCALAPPDATA%/KiNoTch/devflow-mcp-releases/
  active.json                    {"schema_version":2,"sha":"<40-hex>","tree_sha256":"<64-hex>",
                                 "previous_sha":null,"previous_tree_sha256":null}
  updates.hold                   存在中は自動更新停止（rollbackが作成）
  releases/<sha>/tools/devflow_mcp.py
  releases/<prior_sha>/...
```

The marker contains no token. Corrupt or missing installed releases fail closed.
When no marker exists, the original configured immutable script is launched.

## Updater execution

The standalone `tools/devflow_mcp_release_manager.py` is copied once beside
the launcher for future invocations. Example (paths are illustrative):

```powershell
& <PYTHON311_VENV> <INSTALLED_RELEASE_MANAGER> check --repo <TRUSTED_LOCAL_DEVFLOW_GIT_CLONE> --gh <INSTALLED_GH_EXE> --fallback <ORIGINAL_MCP_SCRIPT>
& <PYTHON311_VENV> <INSTALLED_RELEASE_MANAGER> status --repo <TRUSTED_LOCAL_DEVFLOW_GIT_CLONE> --gh <INSTALLED_GH_EXE> --fallback <ORIGINAL_MCP_SCRIPT>
& <PYTHON311_VENV> <INSTALLED_RELEASE_MANAGER> rollback --repo <TRUSTED_LOCAL_DEVFLOW_GIT_CLONE> --gh <INSTALLED_GH_EXE> --fallback <ORIGINAL_MCP_SCRIPT>
& <PYTHON311_VENV> <INSTALLED_RELEASE_MANAGER> resume --repo <TRUSTED_LOCAL_DEVFLOW_GIT_CLONE> --gh <INSTALLED_GH_EXE> --fallback <ORIGINAL_MCP_SCRIPT>
```

The updater and shared `devflow_mcp_catalog.py` admission module are installed together at the protected entry point, after review and the one-time authorized migration (#805). The updater first checks the current release integrity and the persistent update hold. While held, `check` returns `HELD ACTIVE <sha>` or `HELD LEGACY` without fetching, staging or promotion. Otherwise it performs, in order:

1. Restrict Git remote origin to `kinoko34077/devflow`.
2. Compare GitHub's `main` SHA to newly fetched `origin/main`. Require
   the unique successful `project-sync-tests.yml` main-push workflow run for
   that exact SHA and both successful `verify` and `mcp-stdio-python311` jobs
   belonging to that run. Unrelated commit check-runs are not enumerated.
3. Stage a Git archive of that SHA in a temporary new directory, without
   touching a running source clone or virtual environment.
4. Execute bounded Windows local Python unit contract tests (Devflow MCP Core,
   Human Portfolio, release manager). The complete suite is run on GitHub CI.
5. With existing `gh auth` and no stored token, launch real read-only MCP
   stdio and check `initialize`, the observed complete dynamic tool catalog, the
   shared required-call contract and live `bootstrap_repository` / `get_human_portfolio`.
   The old release is retained, not started merely to compare catalogs.
   This intentionally does not re-prove old-worker startup on every promotion;
   rollback selection remains integrity-checked and the actual runtime can recover. Preserve the registered MCP environment except
   for `PYTHONPATH`: the launcher and smoke both bind it to the selected script's
   own release root, and the unit test process uses its staged source root.
   A legacy checkout path would otherwise import old `tools.*` modules even
   when the new script is selected. The original fallback uses its own root.
   Do not persist credentials or print environment values. Reject duplicate or reserved names,
   invalid schemas, incomplete catalogs, explicit incompatible side-effect annotations,
   or missing/incompatible essential calls. New tool names must explicitly declare
   readOnlyHint=true; only the verified original read-only names can omit the
   declaration for legacy fallback compatibility. This does not establish authority.
   Do not require a fixed total tool count or
   equality with the prior catalog. This is structural admission, not semantic proof;
   existing reviewed-source, CI, authority and runtime gates remain required.
6. Record the verified staged tree SHA-256 digest alongside the active commit SHA,
   then atomically replace the active marker. Both the launcher and manager
   re-hash every relative path and file before using an active release.
   Both real MCP and local tests disable Python bytecode writes into the staged
   tree. Failure before marker replacement keeps the prior version selected.
   A pre-existing target is never moved, overwritten, or executed as a
   candidate. Rebuild and test in a fresh stage; reuse the existing directory
   only when its complete digest matches those verified bytes. On mismatch,
   block promotion and preserve the directory for investigation. Previous
   releases remain at their original paths for rollback and in-flight MCP
   processes. A marker-write failure retains the verified target for safe retry.

定期実行は既存の共通PC自動実行基盤 [#1120](https://github.com/kinoko34077/devflow/issues/1120) の
`AutoRunner/jobs.json` へ固定argvの単発 `check` Jobを登録する。周期は60分、共通runnerの
待機・再試行・重複防止・非表示起動・実行結果記録をそのまま利用する。
MCP専用Windows Task、常駐プロセス、追加の待機ループを作らない。
共通runnerにはMCPの認証・取得・検証・版選択を実装しない。
個別managerの排他は手動rollback/resumeとの競合を防ぐため維持する。
初回は無効登録または手動検証とし、実行環境の保護・既存登録との一致・実stdio・
rollbackの受入後のみ有効化する。既存ジョブとTaskの権限を変更しない。
共通runnerの記録はJob ID・結果・終了コードのみで、認証情報を保存しない。

## Rollback and safety boundaries

`rollback` first creates a durable `updates.hold` under the manager lock, then switches back to the previous verified SHA. On the first activation, it removes the active marker and restores the **original immutable fallback** without editing `config.toml`. The hold remains even after failed rollback or a crash between the two steps; the scheduler does not automatically promote any SHA while held. `status` reports the held selection. Only an explicit `resume` verifies the selected release (or the original fallback path) and removes the hold; it does not itself promote or launch a candidate. The next `check` uses the normal verification gates. Keep the backed-up launcher separately for full uninstall.

Only **newly created MCP processes** observe a changed marker. Existing Codex
chat tool catalogs and running MCP servers do not become new code by changing a
file. Never automatically kill the Codex app, call global MCP reload, or
resend an ambiguous write call. Codex connection recovery and dynamic tool
publication remain owned by [#869](https://github.com/kinoko34077/devflow/issues/869);
connection-local worker exchange is owned by [#1138](https://github.com/kinoko34077/devflow/issues/1138) ; the narrowly resumed shared admission contract is owned by [#805](https://github.com/kinoko34077/devflow/issues/805) .

Changes to nonessential tools or optional inputs do not alone block promotion.
Essential call incompatibility, invalid catalog, failed smoke, missing exact-head CI
or any existing integrity/authority gate failure retains the prior selection.
A running client may have a stale tool catalog: automatic in-session refresh and
localized compatibility fallback require the separate #1138 acceptance.

## P2-A / P2-B / P2-C：復旧と実行時完全性の境界（DFM02）

- **部分切替・旧稼働版の保持**：Windows実fixtureで稼働中Pythonのsource directory移動が成功し、後続ファイル読取が失敗した。inactiveであっても既存版を移動・上書きしない。GitHubの検証済みSHAから新規stageを再構築・試験し、既存版がその全バイトdigestと一致する場合に限り元の場所で再利用する。不一致は旧markerを保持しBLOCKED。marker書換え失敗時は検証済みdirを保持し、同様に再試験・一致確認後に再試行できる。破損や未知の既存dirは自動で隔離/消去しない。稼働プロセスへの影響がなく安全に復旧できることを人間が確認した場合のみ、別の明示操作で処置する。
- **起動時の検証**：`active.json` のschema version 2は、検証済みreleaseのSHAだけでなく、全相対パスと全ファイルバイトを含むSHA-256を保持する。launcherは `gh auth token` の実行**前**にハッシュ、パスリダイレクト、schemaを確認し、不一致ならMCPを起動しない。管理コマンドの `UP_TO_DATE` 判定も同じ検証を行う。
- **rollback**：前の版への復帰では、新規に読み取った改変済み内容を「検証済み」に昇格させず、切替前に保持していた `previous_tree_sha256` と照合する。初回有効化の取り消しは元の固定launcher・fallbackへ戻す。schema v1の未検証markerは互換性を仮定せず拒否する（現時点では新方式未導入）。
- **ロールバックの持続（P2-C）**：`updates.hold` の存在中は、同じSHAだけでなく将来のmainへの自動昇格も停止する。空ファイルも停止扱いとし、切替失敗時にも停止を解除しない。`resume` は現行版を確認して停止だけを解除し、次の `check` が通常の検証を再開する。
- **競合防止**：managerはOSのプロセス連動ファイルロックを利用して `check`・`status`・`rollback`・`resume` を排他し、クラッシュ後に永続的なstale lockを残さない。Scheduler側も重複起動を禁止する。
- **残る権限境界**：markerと安定launcher自体の書換え権限を持つ、同一ユーザー権限の攻撃者に対してSHA-256だけでは防御できない。改変検出は「markerを信頼できる」ことが前提であり、検証終了後からプロセス起動までのファイル差替え競合も完全に消せない。DSKTP-SSD2での導入前に、実際のACL・Codex sandboxの書込み範囲・親ディレクトリの保護とプロセス起動経路を確認する。検証不能なら自動更新は有効化しない。
- **互換性の限界**：入力schemaの一致はツールの機能がread-onlyである証明ではない。各版はmain側の正式レビュー・Required CIに依存する。固定tool数ではなく共通catalog受入判定と実必須呼出を検査する。既存会話の動的catalog更新は#1138の別受入とする。
