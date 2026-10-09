// Unpublished Cloudflare Worker proof-of-implementation for devflow#395.
// Security/credential/installation/deployment gates remain human-controlled.
import { DispatchPolicyError, validateDispatchRequest } from "./policy.mjs";

const textEncoder = new TextEncoder();
const API = "https://api.github.com";
const API_VERSION = "2022-11-28";
const MAX_BODY_BYTES = 2048;

function reply(status, message) {
  return new Response(JSON.stringify(message), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function base64Url(bytes) {
  const array = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  for (const b of array) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function pemToBytes(pem) {
  if (typeof pem !== "string" ||
      !/^-----BEGIN PRIVATE KEY-----[\s\S]+-----END PRIVATE KEY-----\s*$/.test(pem)) {
    throw new Error("INVALID_APP_KEY");
  }
  const der = pem.replace(/-----BEGIN PRIVATE KEY-----|-----END PRIVATE KEY-----|\s/g, "");
  return Uint8Array.from(atob(der), (character) => character.charCodeAt(0));
}

export async function signAppJwt(appId, privateKeyPem, nowSeconds) {
  if (!/^[0-9]+$/.test(String(appId))) throw new Error("INVALID_APP_ID");
  const key = await crypto.subtle.importKey("pkcs8", pemToBytes(privateKeyPem), {
    name: "RSASSA-PKCS1-v1_5", hash: "SHA-256",
  }, false, ["sign"]);
  const header = base64Url(textEncoder.encode(JSON.stringify({alg: "RS256", typ: "JWT"})));
  const payload = base64Url(textEncoder.encode(JSON.stringify({
    iat: nowSeconds - 60, exp: nowSeconds + 480, iss: String(appId),
  })));
  const input = header + "." + payload;
  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5", key, textEncoder.encode(input),
  );
  return input + "." + base64Url(signature);
}

async function sameSecret(a, b) {
  if (typeof a !== "string" || typeof b !== "string" ||
      b.length < 32 || a.length > 1024) return false;
  const [digestA, digestB] = await Promise.all([
    crypto.subtle.digest("SHA-256", textEncoder.encode(a)),
    crypto.subtle.digest("SHA-256", textEncoder.encode(b)),
  ]);
  let diff = 0;
  const aa = new Uint8Array(digestA), bb = new Uint8Array(digestB);
  for (let i = 0; i < aa.length; i++) diff |= aa[i] ^ bb[i];
  return diff === 0;
}

async function readSmallJson(request) {
  const contentType = request.headers.get("content-type") || "";
  if (!/^application\/json(?:\s*;|\s*$)/i.test(contentType)) {
    throw new DispatchPolicyError("INVALID_JSON_BODY", 400);
  }
  const declared = request.headers.get("content-length");
  if (declared && (!/^\d+$/.test(declared) || Number(declared) > MAX_BODY_BYTES)) {
    throw new DispatchPolicyError("INVALID_JSON_BODY", 400);
  }
  const reader = request.body?.getReader();
  if (!reader) throw new DispatchPolicyError("INVALID_JSON_BODY", 400);
  let size = 0;
  const parts = [];
  try {
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      size += value.length;
      if (size > MAX_BODY_BYTES) {
        await reader.cancel();
        throw new DispatchPolicyError("INVALID_JSON_BODY", 400);
      }
      parts.push(value);
    }
    const full = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) { full.set(part, offset); offset += part.length; }
    return JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(full));
  } catch (error) {
    if (error instanceof DispatchPolicyError) throw error;
    throw new DispatchPolicyError("INVALID_JSON_BODY", 400);
  }
}

export function createHandler({
  githubFetch = fetch,
  jwtFactory = signAppJwt,
  clock = () => Math.floor(Date.now() / 1000),
} = {}) {
  return async function handle(request, env) {
    const url = new URL(request.url);
    if (request.method !== "POST" || url.pathname !== "/v1/dispatch" ||
        url.search !== "") return reply(404, {error: "NOT_FOUND"});
    if (!env || !env.CLIENT_API_TOKEN || !env.GITHUB_APP_ID ||
        !env.GITHUB_INSTALLATION_ID || !env.GITHUB_APP_PRIVATE_KEY) {
      return reply(503, {error: "NOT_CONFIGURED"});
    }
    const auth = request.headers.get("authorization") || "";
    if (!await sameSecret(auth, "Bearer " + env.CLIENT_API_TOKEN)) {
      return reply(401, {error: "UNAUTHORIZED"});
    }
    let dispatch;
    try {
      dispatch = validateDispatchRequest(await readSmallJson(request));
    } catch (error) {
      return error instanceof DispatchPolicyError
        ? reply(error.status, {error: error.message})
        : reply(400, {error: "INVALID_REQUEST"});
    }
    if (!/^\d+$/.test(String(env.GITHUB_INSTALLATION_ID))) {
      return reply(503, {error: "NOT_CONFIGURED"});
    }
    try {
      const jwt = await jwtFactory(
        env.GITHUB_APP_ID, env.GITHUB_APP_PRIVATE_KEY, clock(),
      );
      const tokenReply = await githubFetch(
        API + "/app/installations/" + env.GITHUB_INSTALLATION_ID + "/access_tokens",
        {
          method: "POST",
          headers: {
            "accept": "application/vnd.github+json",
            "authorization": "Bearer " + jwt,
            "content-type": "application/json",
            "x-github-api-version": API_VERSION,
          },
          body: JSON.stringify({
            repositories: [dispatch.repoName],
            permissions: {actions: "write"},
          }),
        },
      );
      if (!tokenReply.ok) return reply(502, {error: "APP_TOKEN_FAILED"});
      const tokenBody = await tokenReply.json();
      if (typeof tokenBody.token !== "string" || !tokenBody.token) {
        return reply(502, {error: "APP_TOKEN_FAILED"});
      }
      const [owner, name] = dispatch.repository.split("/");
      const dispatchReply = await githubFetch(
        API + "/repos/" + owner + "/" + name + "/actions/workflows/" +
          dispatch.workflow + "/dispatches",
        {
          method: "POST",
          headers: {
            "accept": "application/vnd.github+json",
            "authorization": "Bearer " + tokenBody.token,
            "content-type": "application/json",
            "x-github-api-version": API_VERSION,
          },
          body: JSON.stringify({ref: dispatch.ref, inputs: dispatch.inputs}),
        },
      );
      if (!dispatchReply.ok) {
        return reply(502, {error: "GITHUB_DISPATCH_FAILED"});
      }
      // A successful dispatch API call is NOT proof of workflow execution/success.
      // A separate Actions-run and canonical Issue readback is required.
      return reply(202, {
        state: "DISPATCH_REQUESTED",
        repository: dispatch.repository, workflow: dispatch.workflow,
        ref: dispatch.ref, mode: dispatch.inputs.mode,
        verification: "REQUIRED",
      });
    } catch (_error) {
      // Never echo credentials, upstream HTML, or arbitrary GraphQL/API bodies.
      return reply(502, {error: "UPSTREAM_UNAVAILABLE"});
    }
  };
}

export default {fetch: createHandler()};
