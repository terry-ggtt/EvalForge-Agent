import assert from "node:assert/strict";
import { after, test } from "node:test";
import { createServer } from "vite";

// Vite supplies the real client import.meta.env without adding another transpiler or request client.
const server = await createServer({ server: { middlewareMode: true }, appType: "custom" });
const jobs = await server.ssrLoadModule("/src/api/evaluationJobs.ts");
const { ApiClientError } = await server.ssrLoadModule("/src/api/client.ts");
after(
  /** @returns Closes Vite's watcher after the contract checks. */
  async () => { await server.close(); },
);

test("five API wrappers encode identifiers, filters and actual HTTP methods/payloads",
  /** @param context Built-in test mocks. @returns Checks the existing request client contract without a live server. */
  async (context) => {
    const calls = [];
    context.mock.method(globalThis, "fetch",
      /** @param url Outgoing address. @param init Existing client request options. @returns Minimal successful HTTP JSON response. */
      async (url, init) => {
        calls.push({ url, init });
        return new Response(JSON.stringify({ job_id: "accepted" }), { status: 200 });
      },
    );
    const controller = new AbortController();
    const payload = { name: "evaluation", dataset_version: "v1", agent_version: "a1", cases: [] };
    await jobs.createEvaluationJob(payload);
    await jobs.getEvaluationJobs({ status: "cancel_requested", limit: 20, offset: 40 }, controller.signal);
    await jobs.getEvaluationJob("id /?#", controller.signal);
    await jobs.getEvaluationJobProgress("id /?#", controller.signal);
    await jobs.cancelEvaluationJob("id /?#");
    assert.equal(calls.length, 5);
    assert.equal(calls[0].init.method, "POST");
    assert.deepEqual(JSON.parse(calls[0].init.body), payload);
    assert.equal(calls[0].init.headers["Content-Type"], "application/json");
    const query = new URL(calls[1].url).searchParams;
    assert.equal(query.get("status"), "cancel_requested");
    assert.equal(query.get("limit"), "20");
    assert.equal(query.get("offset"), "40");
    assert.equal(calls[1].init.signal, controller.signal);
    assert.ok(calls[2].url.endsWith("/evaluation-jobs/id%20%2F%3F%23"));
    assert.ok(calls[3].url.endsWith("/evaluation-jobs/id%20%2F%3F%23/progress"));
    assert.ok(calls[4].url.endsWith("/evaluation-jobs/id%20%2F%3F%23/cancel"));
    assert.equal(calls[4].init.method, "POST");
    const all = await jobs.getEvaluationJobs({ status: "", limit: 20, offset: 0 });
    assert.equal(all.job_id, "accepted");
    assert.equal(new URL(calls[5].url).searchParams.has("status"), false);
  });

test("cache keys isolate job identity, status and server pagination",
  /** @returns Checks filters and pages cannot reuse another response. */
  () => {
    assert.notDeepEqual(jobs.evaluationJobKeys.detail("a"), jobs.evaluationJobKeys.detail("b"));
    const base = { status: "running", limit: 20, offset: 0 };
    assert.notDeepEqual(jobs.evaluationJobKeys.list(base), jobs.evaluationJobKeys.list({ ...base, status: "queued" }));
    assert.notDeepEqual(jobs.evaluationJobKeys.list(base), jobs.evaluationJobKeys.list({ ...base, offset: 20 }));
    assert.notDeepEqual(jobs.evaluationJobKeys.list(base), jobs.evaluationJobKeys.list({ ...base, limit: 50 }));
  });

test("API errors retain ApiClientError status, backend code, message and details",
  /** @param context Built-in test mocks. @returns Ensures cancellation failure uses existing error semantics. */
  async (context) => {
    context.mock.method(globalThis, "fetch",
      /** @returns Standard backend conflict response. */
      async () => new Response(JSON.stringify({
        error: { code: "job_conflict", message: "Job already finished", details: { job_id: "a" } },
      }), { status: 409 }),
    );
    await assert.rejects(jobs.cancelEvaluationJob("a"),
      /** @param error Rejected client error. @returns Whether all existing error fields survived. */
      (error) => error instanceof ApiClientError && error.status === 409
        && error.code === "job_conflict" && error.message === "Job already finished"
        && error.details.job_id === "a",
    );
  });
