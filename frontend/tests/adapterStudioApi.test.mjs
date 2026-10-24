import assert from "node:assert/strict";
import { after, test } from "node:test";
import { createServer } from "vite";

const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: "custom" });
const { registryRequest, registryId } = await server.ssrLoadModule("/src/api/adapterStudio.ts");
const { ApiClientError } = await server.ssrLoadModule("/src/api/client.ts");
const { getEvaluationJob } = await server.ssrLoadModule("/src/api/evaluationJobs.ts");
after(/** @returns Releases Vite watchers. */ async () => { await server.close(); });

test("Registry reuses API client, escapes IDs, sends commands once and never leaks auth to legacy APIs",
  /** @param context Native mock lifecycle. @returns Checks HTTP routes/body/auth/cancellation and explicit verbs. */
  async context => {
    const calls = [];
    context.mock.method(globalThis, "fetch",
      /** @param url Target. @param init Request options. @returns Fake successful JSON. */
      async (url, init) => { calls.push({ url, init }); return new Response('{"ok":true}'); });
    const signal = new AbortController().signal;
    const path = `/samples/${registryId("id /?#")}`;
    await registryRequest("session-token", path, undefined, signal);
    await registryRequest("session-token", "/candidates/id/review", { decision: "approve", validation_id: "v", evidence_digest: "digest", note: "human" });
    await registryRequest("session-token", "/candidates/id/publish", { review_id: "audit" });
    await getEvaluationJob("legacy");
    assert.ok(calls[0].url.endsWith("/adapter-registry/samples/id%20%2F%3F%23"));
    assert.equal(calls[0].init.signal, signal);
    assert.equal(calls[0].init.method, "GET");
    assert.equal(calls[0].init.headers.Authorization, "Bearer session-token");
    assert.equal(calls[1].init.method, "POST");
    assert.equal(JSON.parse(calls[1].init.body).note, "human");
    assert.deepEqual(JSON.parse(calls[2].init.body), { review_id: "audit" });
    assert.equal(calls[3].init.headers.Authorization, undefined);
    assert.equal(calls.length, 4);
  });

test("Registry errors retain authorization, stale evidence and disabled-service failures",
  /** @param context Native mock lifecycle. @returns Verifies exact failures without synthetic success or automatic retry. */
  async context => {
    for (const status of [401, 403, 409, 503]) {
      const mock = context.mock.method(globalThis, "fetch",
        /** @returns Existing safe Registry error envelope. */
        async () => new Response('{"error":{"code":"registry_failure","message":"registry_failure"}}', { status }));
      await assert.rejects(registryRequest("bad", "/profiles"),
        /** @param error Rejection. @returns Preserved code/status. */
        error => error instanceof ApiClientError && error.status === status && error.code === "registry_failure");
      assert.equal(mock.mock.callCount(), 1); mock.mock.restore();
    }
  });
