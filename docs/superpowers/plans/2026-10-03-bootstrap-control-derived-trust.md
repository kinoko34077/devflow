# devflow#315: Bootstrap-derived Control trust

## Goal

Allow the MCP to accept a bootstrap-generated `[REPO]` Control only when a
verifiable provenance chain connects it to a trusted `[REPO CREATE]` request.
Keep direct OWNER/MEMBER/COLLABORATOR Control trust unchanged and reject
arbitrary bot-authored or incomplete chains.

## Plan

1. Add RED tests covering the positive existing UniverseGenome chain and the
   required negative cases: arbitrary bot Control, untrusted request author,
   request/target mismatch, missing target provenance, non-terminal request,
   duplicate Controls, and malformed provenance.
2. Implement a small shared provenance parser/renderer and extend the
   read-only GitHub adapter with the minimum issue-comment and repository-file
   reads needed by the verifier.
3. Add derived-trust verification to the MCP service. The verifier will check
   the exact devflow repository and Control title/uniqueness, the trusted
   request author and exact `[REPO CREATE]` payload, a successful terminal
   bootstrap comment, the Control's request provenance, and the exact target
   `.github/repository-bootstrap.json` contents. Existing generated Controls
   are supported through their canonical legacy text; newly generated Controls
   receive an explicit machine-readable provenance block.
4. Update bootstrap and MCP operations/spec documentation, then run focused,
   package, and full regression tests plus static compilation.
5. Audit the exact branch head, create the PR, run CI, record the review and
   merge/main verification on #315, then re-run the UniverseGenome bootstrap
   path and reconcile the parent execution cursor.

## Verification gates

- RED before production implementation.
- GREEN focused tests, then all devflow tests and `py_compile`.
- Exact-head diff audit and manual security review of every trust predicate.
- Post-merge devflow MCP bootstrap succeeds for
  `kinoko34077/UniverseGenome` without changing #314.
