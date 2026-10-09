import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {validateDispatchRequest, DispatchPolicyError} from "./policy.mjs";
import {createHandler, signAppJwt} from "./worker.mjs";
import {reserveDispatch, finalizeDispatch} from "./gate-state.mjs";

if (!globalThis.crypto) globalThis.crypto = webcrypto;
const VALID = {repository: "kinoko34077/devflow", workflow: "project-sync.yml",
  ref: "main", inputs: {mode: "verify", issue_number: ""}};
const SECRET = "a".repeat(48);
const ID = "00000000-0000-4000-8000-000000000001";
const ENV = {
  CLIENT_API_TOKEN: SECRET,
  GITHUB_APP_ID: "123",
  GITHUB_INSTALLATION_ID: "456",
  GITHUB_APP_PRIVATE_KEY: "TEST_FIXTURE_NOT_A_KEY",
};
class MemoryStorage {
  constructor() { this.store = new Map(); }
  async transaction(callback) {
    const tx = {
      get: async (key) => Array.isArray(key)
        ? new Map(key.filter(k => this.store.has(k)).map(k => [k, this.store.get(k)]))
        : this.store.get(key),
      put: async (key, value) => { this.store.set(key, value); },
      delete: async (key) => { this.store.delete(key); },
      list: async ({prefix}) => new Map(
        [...this.store].filter(([key]) => key.startsWith(prefix))
      ),
    };
    return callback(tx);
  }
}
function gateEnv(now = 1700000000) {
  const state = new MemoryStorage();
  return {...ENV,
    DISPATCH_GATE: {
      getByName: (key) => {
        assert.equal(key, "v1-global");
        return {
          fetch: async (req) => {
            const data = await req.json();
            const path = new URL(req.url).pathname;
            const result = path === "/reserve"
              ? await reserveDispatch(state, data, now)
              : await finalizeDispatch(state, data.id, data.decision);
            return Response.json(result, {status: result.status});
          },
        };
      },
    },
    _store: state,
  };
}
const authorizedRequest = (body = VALID, token = SECRET, id = ID) =>
  new Request("https://bridge.example/v1/dispatch", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "authorization": "Bearer " + token,
      "x-request-id": id,
    },
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
  const unauthorized = await handler(authorizedRequest(VALID, "wrong"), gateEnv());
  assert.equal(unauthorized.status, 401);
  const forbidden = await handler(authorizedRequest({...VALID, workflow: "deploy.yml"}), gateEnv());
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
  const res = await handler(authorizedRequest(), gateEnv());
  assert.equal(res.status, 202);
  const answer = await res.json();
  assert.equal(answer.state, "DISPATCH_REQUESTED");
  assert.equal(answer.verification, "REQUIRED");
  assert.equal(answer.request_id, ID);
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
  const result = await handler(authorizedRequest(), gateEnv());
  assert.equal(result.status, 502);
  assert.doesNotMatch(await result.text(), /sensitive upstream details/);
});

test("persistent nonce survives retry and prevents another GitHub call", async () => {
  const env = gateEnv();
  let calls = 0;
  const handler = createHandler({
    jwtFactory: async () => "test.jwt",
    githubFetch: async (url) => {
      calls++;
      return url.includes("access_tokens")
        ? Response.json({token: "test-installation"})
        : new Response(null, {status: 204});
    },
  });
  assert.equal((await handler(authorizedRequest(), env)).status, 202);
  assert.equal((await handler(authorizedRequest(), env)).status, 409);
  assert.equal(calls, 2); // one mint + one dispatch
  assert.equal(env._store.store.get("request:" + ID).state, "REQUESTED");
});
test("replay gate rejects rapid second intent, preserves audit and counts", async () => {
  const state = new MemoryStorage();
  const request = {id: ID, repository: VALID.repository,
    workflow: VALID.workflow, mode: "reconcile"};
  assert.equal((await reserveDispatch(state, request, 1700000000)).status, 200);
  assert.equal((await reserveDispatch(state, {...request, id: "00000000-0000-4000-8000-000000000002"}, 1700000001)).status, 429);
  assert.equal((await reserveDispatch(state, request, 1700000004)).status, 409);
  assert.equal((await finalizeDispatch(state, ID, "AMBIGUOUS")).status, 200);
  assert.equal((await reserveDispatch(state, request, 1700000006)).status, 409);
});
test("gateway fails closed if durable ledger binding missing", async () => {
  let calls = 0;
  const handler = createHandler({githubFetch: async () => {calls++; throw Error("unexpected");}});
  const reply = await handler(authorizedRequest(), ENV);
  assert.equal(reply.status, 503);
  assert.equal(calls, 0);
});
test("ambiguous upstream dispatch never replays same UUID", async () => {
  const env = gateEnv();
  let calls = 0;
  const handler = createHandler({
    jwtFactory: async () => "test.jwt",
    githubFetch: async (url) => {
      calls++;
      return url.includes("access_tokens")
        ? Response.json({token: "test-installation"})
        : new Response("maybe accepted", {status: 504});
    },
  });
  const failure = await handler(authorizedRequest(), env);
  assert.equal(failure.status, 502);
  assert.doesNotMatch(await failure.text(), /maybe accepted/);
  assert.equal(env._store.store.get("request:" + ID).state, "AMBIGUOUS");
  assert.equal((await handler(authorizedRequest(), env)).status, 409);
  assert.equal(calls, 2);
});
test("invalid missing request ID is rejected before installation token mint", async () => {
  let calls = 0;
  const env = gateEnv();
  const handler = createHandler({githubFetch: async () => {calls++; throw Error("unexpected");}});
  const req = authorizedRequest(VALID, SECRET, "bad-uuid");
  const result = await handler(req, env);
  assert.equal(result.status, 400);
  assert.equal(calls, 0);
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
