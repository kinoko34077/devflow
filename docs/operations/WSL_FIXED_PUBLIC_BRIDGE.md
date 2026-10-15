# F3C existing-owner-PC WSL2 bridge — Public fixed recipe only

Owner: [devflow #610](https://github.com/kinoko34077/devflow/issues/610), parent #541. User explicitly authorized existing WSL2 for Actions-independent execution on 2026-10-16. This is a bounded, reversible **manual/on-demand** implementation. It does NOT install any service or authorize any Private, Cloud or Github Claim operation.

## Actual live proof (before this module)
On DSKTP-SSD2, `wsl.exe --distribution Ubuntu-24.04 --exec` started existing stopped Ubuntu; Linux 6.18.54.1-microsoft-standard-WSL2, Python 3.12.3. WSL independently downloaded the existing accepted Public F3A source at commit `fb1f353ddf5438407a5e806682a4b37611cf346d`, checked git blob `cbe42086a50cd1bf44e4198c97cce96a6bc36396`, ran one fixed read-only local child process and obtained SHA-256 `48022e9a9b0ba8912856ec1866cf91e0ff6566e4d6f448425911137c72d810fb` with exit code 0. No Actions scheduler or CI minutes were used. Detailed evidence: #610.

## Safe manual invocation
From a trusted **Windows** devflow checkout with the existing WSL2 Ubuntu distribution already installed:

```powershell
python -m tools.wsl_fixed_public_bridge
```

This starts Ubuntu if needed, downloads **one exact public Python blob** from an immutable full commit, validates its Git object hash and evaluates the accepted fixed sha256 recipe in a temporary Linux child process. It returns only bounded JSON flags/status, no source, task body, stdout/stderr, secrets or private data. No daemon, public port, GitHub token or service installation. One call runs once, with an overall timeout.

Tests: `python -m unittest tests.test_wsl_fixed_public_bridge -v`. The module's tests fake Windows/WSL invocation; actual owner-PC WSL proof is the separately recorded real observation.

## Security and progression gates
- WSL2 can access mounted Windows drives and integrate with the Windows user's environment. **WSL2 is not a security boundary for untrusted PR code or a credential-bearing CI sandbox.** Only this fixed, public, preverified recipe is accepted.
- HTTP fetch and Git content identity are not GitHub actor authentication, issuer/nonce replay protection, a durable job queue, genuine GitHub Check authority or native CI. `authenticated=false`, `isolated_host_verified=false`, `claim_authority=false` by construction.
- No trusted independent **remote trigger** nor public ingress has been activated. To reach a real F3C externally callable worker, separately approve a specific safe ingress, one source identity/nonce trust chain, durable receipt and resource controls. Prefer authenticated outbound pull; do not open router ports or start resident listeners without further authorization.
- Any Private repository checkout/test, new token/App, credential/permission change, installation/startup automation, privileged Claim migration or paid service remains independently Human-gated. User payment decision remains frozen; no unrelated JPY 2,000 limit.

Code-only WSL wrapper is not a claim that F4/F5 or unattended Actions-independent CI has been delivered.
