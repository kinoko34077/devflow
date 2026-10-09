// V1 admission policy: installation reach is NOT execution authorization.
// Every future repository/workflow must be added through a reviewed policy change.
export const V1_POLICY = Object.freeze({
  "kinoko34077/devflow": Object.freeze({
    "project-sync.yml": Object.freeze({
      ref: "main",
      modes: Object.freeze(["verify", "reconcile"]),
    }),
  }),
});

export class DispatchPolicyError extends Error {
  constructor(message = "DISPATCH_NOT_ALLOWED", status = 403) {
    super(message);
    this.name = "DispatchPolicyError";
    this.status = status;
  }
}

const isPlainObject = (value) =>
  value !== null &&
  typeof value === "object" &&
  !Array.isArray(value) &&
  (Object.getPrototypeOf(value) === Object.prototype ||
    Object.getPrototypeOf(value) === null);

const exactKeys = (value, keys) => {
  const found = Object.keys(value).sort();
  const expected = [...keys].sort();
  return found.length === expected.length &&
    found.every((key, index) => key === expected[index]);
};

export function validateDispatchRequest(body, policy = V1_POLICY) {
  if (!isPlainObject(body) ||
      !exactKeys(body, ["repository", "workflow", "ref", "inputs"]) ||
      typeof body.repository !== "string" || body.repository.length > 128 ||
      typeof body.workflow !== "string" || body.workflow.length > 120 ||
      typeof body.ref !== "string" || body.ref.length > 120 ||
      !isPlainObject(body.inputs) ||
      !exactKeys(body.inputs, ["mode", "issue_number"])) {
    throw new DispatchPolicyError();
  }
  const repositoryPolicy = Object.hasOwn(policy, body.repository)
    ? policy[body.repository] : null;
  const workflowPolicy = repositoryPolicy && Object.hasOwn(repositoryPolicy, body.workflow)
    ? repositoryPolicy[body.workflow] : null;
  if (!workflowPolicy ||
      body.ref !== workflowPolicy.ref ||
      typeof body.inputs.mode !== "string" ||
      !workflowPolicy.modes.includes(body.inputs.mode) ||
      body.inputs.issue_number !== "") {
    throw new DispatchPolicyError();
  }
  const [owner, name] = body.repository.split("/");
  if (!/^[A-Za-z0-9-]+$/.test(owner) || !/^[A-Za-z0-9_.-]+$/.test(name)) {
    throw new DispatchPolicyError();
  }
  return Object.freeze({
    repository: body.repository,
    repoName: name,
    workflow: body.workflow,
    ref: workflowPolicy.ref,
    inputs: Object.freeze({mode: body.inputs.mode, issue_number: ""}),
  });
}
