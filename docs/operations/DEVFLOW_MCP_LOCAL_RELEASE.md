# Codex Devflow MCP — verified local release selector (#1111)

This procedure applies **only to the authorized KiNoTch. Windows Codex**
registration named \`kinotch_devflow\`. It is not a global repository bootstrap,
MCP protocol versioning scheme, Codex lifecycle fix or claim authority.

## Stable registration

The existing \`~/.codex/config.toml\` keeps its existing Python \`command\` and
the three \`args\`: stable launcher, authenticated \`gh.exe\`, immutable original
\`tools/devflow_mcp.py\`. The launcher file is installed from
\`tools/devflow_mcp_stable_launcher.py\` **once**, after backing up the existing
launcher byte-for-byte. The old third argument is preserved as the fallback.

A local read-only state file determines which *newly started* server is selected:

\`\`\`text
%LOCALAPPDATA%/KiNoTch/devflow-mcp-releases/
  active.json                    {"schema_version":1,"sha":"<40-hex>","previous_sha":null}
  releases/<sha>/tools/devflow_mcp.py
  releases/<prior_sha>/...
\`\`\`

The marker contains no token. Corrupt or missing installed releases fail closed.
When no marker exists, the original configured immutable script is launched.

## Updater execution

The standalone \`tools/devflow_mcp_release_manager.py\` is copied once beside
the launcher for future invocations. Example (paths are illustrative):

\`\`\`powershell
& <PYTHON311_VENV> <INSTALLED_RELEASE_MANAGER> check --repo <TRUSTED_LOCAL_DEVFLOW_GIT_CLONE> --gh <INSTALLED_GH_EXE> --fallback <ORIGINAL_MCP_SCRIPT>
& <PYTHON311_VENV> <INSTALLED_RELEASE_MANAGER> status --repo <TRUSTED_LOCAL_DEVFLOW_GIT_CLONE> --gh <INSTALLED_GH_EXE> --fallback <ORIGINAL_MCP_SCRIPT>
& <PYTHON311_VENV> <INSTALLED_RELEASE_MANAGER> rollback --repo <TRUSTED_LOCAL_DEVFLOW_GIT_CLONE> --gh <INSTALLED_GH_EXE> --fallback <ORIGINAL_MCP_SCRIPT>
\`\`\`

The updater performs, in order:

1. Restrict Git remote origin to \`kinoko34077/devflow\`.
2. Compare GitHub's \`main\` SHA to newly fetched \`origin/main\`. Require
   successful exact-SHA \`verify\` and \`mcp-stdio-python311\` GitHub Actions
   checks (not simply the presence of a workflow name).
3. Stage a Git archive of that SHA in a temporary new directory, without
   touching a running source clone or virtual environment.
4. Execute bounded Windows local Python unit contract tests (Devflow MCP Core,
   Human Portfolio, release manager). The complete suite is run on GitHub CI.
5. With existing \`gh auth\` and no stored token, launch real read-only MCP
   stdio and check \`initialize\`, exactly 16 tools, \`bootstrap_repository\`
   and \`get_human_portfolio\`. Compare existing/new callable tool schemas,
   excluding only descriptions/titles/examples.
6. Install immutable release and atomically replace the active SHA marker.
   Failure anywhere **before** marker replacement leaves the prior version
   selected. For automatic schedule activation, preserve old releases.

A Windows Task Scheduler entry can run \`check\` hourly using the *current
interactive user*, without elevation and with concurrent executions suppressed.
It must be explicitly authorized before installation. No updater runs in
the MCP launcher itself. Task logs record only status and SHA, never token.

## Rollback and safety boundaries

\`rollback\` switches back to the previous verified SHA. On the first
activation, it removes the marker and restores the **original immutable
fallback** without editing \`config.toml\`. Keep the backed-up launcher
separately for full uninstall.

Only **newly created MCP processes** observe a changed marker. Existing Codex
chat tool catalogs and running MCP servers do not become new code by changing a
file. Never automatically kill the Codex app, call global MCP reload, or
resend an ambiguous write call. Codex connection recovery and dynamic tool
publication remain owned by [#869](https://github.com/kinoko34077/devflow/issues/869);
broader tool contract versioning remains [#805 WATCH/DEFER](https://github.com/kinoko34077/devflow/issues/805).

A changed set of callable MCP tool names, required arguments, schemas, or
missing successful exact-head CI **blocks** automatic promotion. Re-check
the user-facing Codex version and compatibility before an explicit
breaking-contract rollout.
