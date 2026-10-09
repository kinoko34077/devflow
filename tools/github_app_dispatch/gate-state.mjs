// Durable, serialized admission ledger. Only the bound Durable Object invokes this.
export const REQUEST_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const HOUR_LIMIT = 12;
const MIN_INTERVAL_SECONDS = 3;
const KEEP_DAYS = 7;

export async function reserveDispatch(storage, request, nowSeconds) {
  const {id, repository, workflow, mode} = request;
  if (!REQUEST_ID_PATTERN.test(id)) return {status: 400, error: "INVALID_REQUEST_ID"};
  return storage.transaction(async (tx) => {
    const prior = await tx.get("request:" + id);
    if (prior !== undefined) return {status: 409, error: "DUPLICATE_REQUEST"};
    const hour = Math.floor(nowSeconds / 3600);
    const limits = await tx.get(["counter:" + hour, "last-dispatch"]);
    const count = limits.get("counter:" + hour) || 0;
    const last = limits.get("last-dispatch") || 0;
    if (count >= HOUR_LIMIT || nowSeconds - last < MIN_INTERVAL_SECONDS) {
      return {status: 429, error: "RATE_LIMITED"};
    }
    // Nonce is reserved before *any* GitHub mutation. Ambiguous outcomes never auto-retry.
    await tx.put("request:" + id, {
      at: nowSeconds, repository, workflow, mode, state: "RESERVED",
    });
    await tx.put("counter:" + hour, count + 1);
    await tx.put("last-dispatch", nowSeconds);
    // Keep latest seven days' audit references. Restrict cleanup to this object.
    const expiry = nowSeconds - KEEP_DAYS * 86400;
    const snapshots = await tx.list({prefix: "request:"});
    for (const [key, value] of snapshots) {
      if (value && value.at < expiry) await tx.delete(key);
    }
    // Sweep stale counters across inactivity gaps, not only one prior hour.
    const counters = await tx.list({prefix: "counter:"});
    for (const [key] of counters) {
      const bucket = Number(key.slice("counter:".length));
      if (Number.isSafeInteger(bucket) && bucket < hour - 2) await tx.delete(key);
    }
    return {status: 200, state: "RESERVED"};
  });
}

export async function finalizeDispatch(storage, id, decision) {
  if (!REQUEST_ID_PATTERN.test(id) ||
      !["REQUESTED", "GITHUB_REJECTED", "AMBIGUOUS"].includes(decision)) {
    return {status: 400, error: "INVALID_COMPLETION"};
  }
  return storage.transaction(async (tx) => {
    const old = await tx.get("request:" + id);
    if (!old || old.state !== "RESERVED") {
      return {status: 409, error: "NO_PENDING_REQUEST"};
    }
    await tx.put("request:" + id, {...old, state: decision});
    return {status: 200, state: decision};
  });
}
