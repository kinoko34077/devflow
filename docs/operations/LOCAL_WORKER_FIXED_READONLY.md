# Actions-independent fixed local Worker — F3-B bounded pilot

Status: code-only and single-shot; owning Issue devflow #605, parent #541. This is not a deployed remote host, runner or GitHub CI replacement.

## Why

Unlike GitHub Self-hosted Actions, a separately invoked local Python subprocess does not depend on Actions dispatch or hosted minutes. This provides a real OS execution primitive distinct from the F2A/F2B/F2C fake backend, without installing a background agent.

## Accepted scope of the code-only candidate

- One allowlisted recipe: python-runtime-version-v1, launched via sys.executable with Python -I -S and an embedded fixed stdout probe. Caller cannot supply shell commands, code, URLs, file paths, arbitrary environment or GitHub credentials.
- Input validates repository, task_ref on that same repository, exact lowercase 40-hex source SHA, READ_ONLY effect and integer deadline from 1 through 10 seconds.
- Runs once in an OS temporary directory, with a minimal process environment and no shell. It returns bounded outcome/exit metadata and a SHA-256 hash, never raw stdout or stderr.
- A successful receipt proves only the fixed interpreter task ran locally. It does not prove execution of the source commit, repository tests, container isolation, GitHub authorization, remote dispatch, host availability or valid Claim state.
- The Python process shares the user OS security context. -I -S, process timeout and temporary working directory are NOT a security sandbox. Never run untrusted PR contents or Private repository scripts with secrets through this adapter.
- Does not open a listening port, poll Jobs, register Actions, install service, create credentials, change permissions, alter Claim #3, submit a Codex Cloud task, or write to GitHub.

## Focused verification

    python -m pytest tests/test_local_worker_fixed_readonly.py -q

This test suite exercises one real local process plus fail-closed inputs, fixed argv, timeout, output overflow, error and secret redaction. The actual host PC has NOT been modified by this code-only candidate.

## First unfinished after accepted F3-B

1. Determine and separately authorize a host isolation mechanism and typed independent job ingress, if an actual always-available Worker is required.
2. Integrate bounded read-only job receipt with the existing central Gateway, without assuming F2 fake Claims grant real authority.
3. Verify native private/public repo access and exact source SHA in a truly isolated, authorized host, then implement effect-time fencing before privileged workflows.
4. Keep Codex Cloud path A owner-PC CLI separate: devflow #597 has accepted read-only diagnostic only; actual current Cloud task dispatch is unverified.

Paid services, new credentials, background resident services, Private source processing, runner registration and Claim cutover remain separate Human gates. No unrelated JPY 2,000 cap applies.
