// Cloudflare Durable Object; reachable only through the private Worker binding.
// Never deployed or instantiated automatically by this repository.
import { DurableObject } from "cloudflare:workers";
import { reserveDispatch, finalizeDispatch } from "./gate-state.mjs";

export class DispatchGate extends DurableObject {
  constructor(ctx, env) { super(ctx, env); }

  async fetch(request) {
    if (request.method !== "POST") return Response.json({error: "INVALID_GATE_METHOD"}, {status: 404});
    try {
      const action = new URL(request.url).pathname;
      const data = await request.json();
      let result;
      if (action === "/reserve") {
        result = await reserveDispatch(this.ctx.storage, data, Math.floor(Date.now() / 1000));
      } else if (action === "/complete") {
        result = await finalizeDispatch(this.ctx.storage, data.id, data.decision);
      } else {
        return Response.json({error: "INVALID_GATE_ACTION"}, {status: 404});
      }
      return Response.json(result, {status: result.status});
    } catch {
      return Response.json({error: "GATE_UNAVAILABLE"}, {status: 503});
    }
  }
}
