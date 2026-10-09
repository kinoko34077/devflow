// Production Worker entrypoint. The local test imports worker.mjs instead
// of the Cloudflare-only Durable Object runtime module.
import worker from "./worker.mjs";
export { DispatchGate } from "./gate-object.mjs";
export default worker;
