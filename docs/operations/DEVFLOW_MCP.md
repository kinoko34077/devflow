# Devflow MCP

`tools/devflow_mcp.py` exposes live `kinoko34077/devflow` operational state to Codex, Claude Code and other MCP clients through a read-only stdio server.

This MCP is an access layer, not a second source of truth. Canonical authority remains:

- devflow Repository Control / Work Order Issues for cross-repository operational state;
- the owning repository for detailed technical truth;
- GitHub Project as display-only.

## Read-only boundary

The server exposes only read operations:

- `bootstrap_repository(repository)`
- `get_repository_control(repository)`
- `list_managed_repositories()`
- `get_issue(repository, issue_number)`
- `get_sync_health()`

The underlying GitHub client implements GET-only REST access. It has no Issue update, PR mutation, merge, branch, credential, release or deployment tool.

## Runtime

Requirements:

- Python 3.10+
- `pip install -r requirements-mcp.txt`

Start directly:

```powershell
py tools/devflow_mcp.py
```

The MCP uses stdio transport.

## GitHub authentication

Public devflow reads can work without a token. A token is recommended for rate limits and required when devflow or a target repository is private/access-controlled.

Token lookup order:

1. `DEVFLOW_GITHUB_TOKEN`
2. `GITHUB_TOKEN`
3. unauthenticated GitHub REST

Use a read-capable token only. Do not commit tokens to this repository, `.mcp.json`, `AGENTS.md`, `CLAUDE.md`, or other shared files.

## Required agent trigger

Connecting an MCP server does not guarantee that an agent will call it. Client instructions must explicitly state when live devflow is required.

Use this rule in Codex/Claude global instructions:

```text
For KiNoTch managed repositories, before answering or acting on current state, resume,
audit, implementation, review, Issue/PR/Work Order or cross-repository work, call the
KiNoTch Devflow MCP `bootstrap_repository` for the current repository. Follow the returned
Repository Control and Canonical Entry Points. Do not substitute chat history, static
.ai-guidelines content, or GitHub Project fields for live Current State. Use Issue-first
reporting for durable detail/evidence/handoff.
```

## Codex

Current Codex supports stdio MCP servers through `~/.codex/config.toml` and shares MCP configuration between CLI and IDE extension.

Example user-level configuration:

```toml
[mcp_servers.kinotchDevflow]
command = "py"
args = ["C:\\path\\to\\devflow\\tools\\devflow_mcp.py"]

[mcp_servers.kinotchGuidelines]
command = "py"
args = ["C:\\path\\to\\.ai-guidelines\\guidelines_mcp.py"]
```

Keep the token in the process environment rather than hard-coding it in the TOML. Verify with:

```powershell
codex mcp list
```

Add the required agent trigger above to user-level `~/.codex/AGENTS.md` (Windows: `%USERPROFILE%\.codex\AGENTS.md`) so Codex calls the MCP automatically when the task depends on live managed-repository state.

Official references:

- https://developers.openai.com/learn/docs-mcp
- https://developers.openai.com/docs/config-file/config-reference

## Claude Code

Claude Code supports local stdio MCP servers and user-scope MCP configuration.

Example:

```powershell
claude mcp add --scope user kinotch-devflow -- py C:\path\to\devflow\tools\devflow_mcp.py
claude mcp add --scope user kinotch-guidelines -- py C:\path\to\.ai-guidelines\guidelines_mcp.py
claude mcp list
```

Add the required agent trigger above to user-level `~/.claude/CLAUDE.md` (Windows: `%USERPROFILE%\.claude\CLAUDE.md`). Claude Code automatically loads this user instruction file for all projects.

Official references:

- https://docs.anthropic.com/docs/claude-code/mcp
- https://docs.anthropic.com/docs/claude-code/memory

## Expected bootstrap flow

For `kinoko34077/<repo>`:

1. call `bootstrap_repository("kinoko34077/<repo>")`;
2. read returned Work Status / Repository State / Audit SHA / Active Work / Next Action;
3. follow returned Canonical Entry Points in the local checkout;
4. read active owning-repository Issue / Work Order / PR as required;
5. inspect task-relevant specs / Current State / code / tests;
6. record durable progress and verification in the owning Issue; update devflow Control only when its cross-repository summary changes.

If the MCP cannot find exactly one open `[REPO] <repo>` Control Issue, it fails instead of guessing managed state.

## Relationship to `.ai-guidelines`

The Guidelines MCP provides static shared coding/spec/UI/UX/usability policy. It must not mirror live Work Status, Audit SHA, Active Work, blockers or Sync Health.

The two MCPs are complementary:

```text
client instructions
  -> Devflow MCP       (live operational state)
  -> Guidelines MCP    (static shared policy)
  -> owning repository (technical canon + implementation)
```
