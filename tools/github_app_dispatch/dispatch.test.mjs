import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {validateDispatchRequest, DispatchPolicyError} from "./policy.mjs";
import {createHandler, signAppJwt} from "./worker.mjs";

if (!globalThis.crypto) globalThis.crypto = webcrypto;
const VALID = {repository: "kinoko34077/devflow", workflow: "project-sync.yml",
  ref: "main", inputs: {mode: "verify", issue_number: ""}};
const SECRET = "a".repeat(48);
const ENV = {
  CLIENT_API_TOKEN: SECRET,
  GITHUB_APP_ID: "123",
  GITHUB_INSTALLATION_ID: "456",
  GITHUB_APP_PRIVATE_KEY: "TEST_FIXTURE_NOT_A_KEY",
};
const authorizedRequest = (body = VALID, token = SECRET) =>
  new Request("https://bridge.example/v1/dispatch", {
    method: "POST",
    headers: {"content-type": "application/json", "authorization": "Bearer " + token},
    body: JSON.stringify(body),
  });

test("policy authorizes exact full-scope verify/reconcile", () => {
  for (const mode of ["verify", "reconcile"]) {
    assert.equal(validateDispatchRequest({...VALID, inputs: {mode, issue_number: ""}}).inputs.mode, mode);
  }
});
test("policy forbids every other repository, workflow, ref or caller-selected issue", () => {
  for (const body of [
    {...VALID, repository: "kinoko34077/UniverseGenome"},
    {...VALID, workflow: "deploy.yml"},
    {...VALID, ref: "feat/untrusted"},
    {...VALID, inputs: {mode: "audit", issue_number: ""}},
    {...VALID, inputs: {mode: "verify", issue_number: "314"}},
    {...VALID, inputs: {...VALID.inputs, extra: "shell"}},
    {...VALID, unexpected: "field"},
    {repository: "kinoko34077/devflow", workflow: "__proto__", ref: "main", inputs: VALID.inputs},
  ]) {
    assert.throws(() => validateDispatchRequest(body), DispatchPolicyError);
  }
});
test("no GitHub call on unauthorized token or non-allowed workflow", async () => {
  let calls = 0;
  const handler = createHandler({
    githubFetch: async () => {calls++; return new Response(null,{status: 204});},
    jwtFactory: async () => "test.jwt",
  });
  const unauthorized = await handler(authorizedRequest(VALID, "wrong"), ENV);
  assert.equal(unauthorized.status, 401);
  const forbidden = await handler(authorizedRequest({...VALID, workflow: "deploy.yml"}), ENV);
  assert.equal(forbidden.status, 403);
  assert.equal(calls, 0);
});
test("dispatch requests only repo-scoped short-lived token then exact allowed workflow", async () => {
  const seen = [];
  const handler = createHandler({
    jwtFactory: async () => "test.jwt",
    githubFetch: async (url, options) => {
      seen.push({url, ...options});
      if (url.includes("/access_tokens")) {
        return Response.json({token: "installation-token"});
      }
      return new Response(null, {status: 204});
    },
  });
  const res = await handler(authorizedRequest(), ENV);
  assert.equal(res.status, 202);
  const answer = await res.json();
  assert.equal(answer.state, "DISPATCH_REQUESTED");
  assert.equal(answer.verification, "REQUIRED");
  assert.equal(seen.length, 2);
  assert.equal(seen[0].url, "https://api.github.com/app/installations/456/access_tokens");
  assert.deepEqual(JSON.parse(seen[0].body), {
    repositories: ["devflow"], permissions: {actions: "write"},
  });
  assert.equal(seen[1].url,
    "https://api.github.com/repos/kinoko34077/devflow/actions/workflows/project-sync.yml/dispatches");
  assert.deepEqual(JSON.parse(seen[1].body), {ref: "main", inputs: {mode: "verify", issue_number: ""}});
  assert.equal(seen[1].headers.authorization, "Bearer installation-token");
});
test("upstream errors stay sanitized and do not claim workflow success", async () => {
  const handler = createHandler({
    jwtFactory: async () => "test.jwt",
    githubFetch: async () => new Response("sensitive upstream details", {status: 403}),
  });
  const result = await handler(authorizedRequest(), ENV);
  assert.equal(result.status, 502);
  assert.doesNotMatch(await result.text(), /sensitive upstream details/);
});
test("JWT is RS256 signed with short expiry, without exposing private key", async () => {
  const pair = await crypto.subtle.generateKey(
    {name: "RSASSA-PKCS1-v1_5", modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256"},
    true, ["sign", "verify"],
  );
  const pkcs8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey));
  const pem = "-----BEGIN PRIVATE KEY-----\n" +
    Buffer.from(pkcs8).toString("base64") + "\n-----END PRIVATE KEY-----";
  const jwt = await signAppJwt("123", pem, 1700000000);
  const [header,payload,signature] = jwt.split(".");
  assert.equal(JSON.parse(Buffer.from(header, "base64url")).alg, "RS256");
  assert.deepEqual(JSON.parse(Buffer.from(payload, "base64url")), {
    iat: 1699999940, exp: 1700000480, iss: "123",
  });
  const ok = await crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5", pair.publicKey,
    Buffer.from(signature, "base64url"), new TextEncoder().encode(header+"."+payload),
  );
  assert.equal(ok, true);
});
