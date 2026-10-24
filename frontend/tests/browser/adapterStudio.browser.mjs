/**
 * Real Chromium interaction tests against a Fake Registry, no live API/model/publishing.
 * Uses an externally supplied existing Playwright installation; no project dependency added.
 * STUDIO_PLAYWRIGHT_MODULE points to playwright/index.mjs; STUDIO_BROWSER_EXECUTABLE to Chrome.
 */
import assert from "node:assert/strict";
import { test, after } from "node:test";
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

if (!process.env.STUDIO_PLAYWRIGHT_MODULE) throw new Error("Set STUDIO_PLAYWRIGHT_MODULE to an existing Playwright module.");
const { chromium } = await import(pathToFileURL(process.env.STUDIO_PLAYWRIGHT_MODULE).href);
const browser = await chromium.launch({ headless: true, executablePath: process.env.STUDIO_BROWSER_EXECUTABLE });
const origin = process.env.STUDIO_BASE_URL ?? "http://127.0.0.1:5173";
const fixture = JSON.parse(await readFile(new URL("../../../backend/tests/fixtures/mini_mapping_agent.json", import.meta.url), "utf8"));
after(/** @returns Closes only this test's browser. */ async () => { await browser.close(); });

/** @param options Failure/disclosure scenario switches. @returns Isolated browser context and fake durable Registry state. */
async function setup(options = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const consoleErrors = [];
  page.on("pageerror", /** @param error Browser uncaught exception. @returns Records runtime failure. */ error => consoleErrors.push(error.message));
  const state = { profiles: [], samples: [], candidates: [], generations: [], validations: [], versions: [], audits: [], generationReads: 0, commands: [], requests: [] };
  const mapping = fixture.repair_reply.mapping;
  const inspection = { success: true, schema_fingerprint: "browser-fixture-fingerprint", differences: [], fields: [
    { path: '$["answer"]', types: ["string"], sample_frequency: 1, nullable: false, missing_occurrences: 0 },
    { path: '$["events"][]["kind"]', types: ["string"], sample_frequency: 1, nullable: false, missing_occurrences: 0 },
    { path: '$["private"]["api_key"]', types: ["string"], sample_frequency: 1, nullable: false, missing_occurrences: 0 },
  ] };
  const reports = [{ l1: "passed", l2: "passed", l3: options.noGolden ? "unverified" : "passed",
    errors: [], warnings: [], unverified: options.noGolden ? [{ code: "golden_required", message: "Missing independent Golden" }] : [],
    release_allowed: !options.noGolden, release_blockers: options.noGolden ? ["semantic_unverified"] : [], golden_fields_verified: [] }];

  await page.route("**/adapter-registry/**",
    /** @param route Intercepted API request. @returns Fake authorized response, recording actual UI commands. */
    async route => {
      const request = route.request(), url = new URL(request.url()), method = request.method();
      const path = url.pathname.replace("/adapter-registry", "");
      const body = method === "POST" ? request.postDataJSON() : undefined;
      state.requests.push({ path, method, body, authorization: request.headers().authorization });
      if (method === "OPTIONS") return route.fulfill({ status: 200, headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "GET,POST,OPTIONS" } });
      if (options.generationNetworkFailure && path.startsWith("/generations/") && !state.networkRecovered) {
        state.generationFailedOnce = true;
        return route.abort("failed");
      }
      let status = 200, data;
      if (options.unauthorized) { status = 401; data = { error: { code: "adapter_authentication_required", message: "adapter_authentication_required" } }; }
      else if (options.forbidden && (path.endsWith("/review") || path.endsWith("/publish"))) {
        status = 403; data = { error: { code: "adapter_forbidden", message: "adapter_forbidden" } };
      } else if (method === "POST") {
        state.commands.push({ path, body });
        if (path === "/profiles") {
          data = { profile_id: "adapter-1", ...body, trace_profile_json: {} }; state.profiles.push(data);
        } else if (path.endsWith("/samples")) {
          data = { sample_id: "sample-1", samples_json: body.samples, inspection_json: inspection, schema_fingerprint: inspection.schema_fingerprint }; state.samples.push(data);
        } else if (path.endsWith("/generations")) {
          data = { generation_id: "generation-1", sample_id: "sample-1", status: "queued", calls_started: 0, reserved_tokens: 0, reserved_cost_nano_usd: 0, checkpoints_json: [] };
          state.generations.push(data);
        } else if (path.endsWith("/candidates")) {
          data = { candidate_id: "candidate-1", sample_id: body.sample_id, generation_id: null, mapping_json: body.mapping, mapping_digest: "mapping-digest", status: "draft" };
          state.candidates.push(data);
        } else if (path.endsWith("/preview")) {
          data = { mapping_results: [{ success: true, result: { output_text: fixture.raw_response.answer,
            trace: fixture.raw_response.events.map(
              /** @param event Raw fixture. @returns Fake canonical counterpart for UI comparison. */
              event => ({ type: "llm_end", timestamp: event.finished, payload: event.span })) },
            events: [{ raw_pointer: "/events/0", raw_event: fixture.raw_response.events[0], normalized_event: { payload: fixture.raw_response.events[0].span } }], errors: [], warnings: [] }] };
        } else if (path.endsWith("/validate")) {
          data = { validation_id: "validation-1", evidence_digest: "e".repeat(64), reports_json: reports, eligible: !options.noGolden };
          state.validations = [data]; state.candidates[0].status = options.noGolden ? "draft" : "validated";
        } else if (path.endsWith("/review")) {
          data = { audit_id: "review-1", candidate_id: "candidate-1", validation_id: body.validation_id, action: body.decision === "approve" ? "review_approved" : "review_rejected" };
          state.audits.push(data); state.candidates[0].status = body.decision === "approve" ? "approved" : "rejected";
        } else if (path.endsWith("/publish")) {
          data = { profile_id: "adapter-1", version: 1, candidate_id: "candidate-1", validation_id: "validation-1", published_by: "human-reviewer",
            published_at: "2026-10-24T12:00:00Z", mapping_digest: "mapping-digest", schema_fingerprint: inspection.schema_fingerprint, mapping_json: mapping, snapshot_json: { sample_id: "sample-1" } };
          state.versions = [data]; state.candidates[0].status = "published";
        }
      } else {
        if (path === "/profiles") data = state.profiles;
        else if (path === "/profiles/adapter-1") data = state.profiles[0];
        else if (path.endsWith("/samples")) data = state.samples.map(
          /** @param sample Immutable batch. @returns Metadata-only listing. */ sample => ({ sample_id: sample.sample_id }));
        else if (path.startsWith("/samples/")) data = state.samples[0];
        else if (path.endsWith("/candidates")) data = state.candidates;
        else if (path.endsWith("/generations")) data = state.generations;
        else if (path.endsWith("/validations")) data = state.validations;
        else if (path.startsWith("/validations/")) data = state.validations[0];
        else if (path.endsWith("/audit")) data = state.audits;
        else if (path.startsWith("/candidates/")) data = state.candidates[0];
        else if (path.startsWith("/generations/")) {
          state.generationReads++;
          const run = state.generations[0];
          run.status = state.generationReads >= 3 ? (options.generationFailure ? "needs_manual_review" : "completed") : "running";
          run.calls_started = 2;
          run.reserved_tokens = 100;
          run.reserved_cost_nano_usd = 2000;
          if (run.status === "completed") {
            run.candidate_id = "candidate-1";
            run.result_json = { reason: "validated", attempts: [
              { index: 0, outcome: "validation_failed", feedback: [{ code: "golden_value_mismatch", layer: "L3" }] },
              { index: 1, outcome: "candidate", feedback: [], proposal: { evidence: [
                { event_source_type: null, target: "$.output_text", source_paths: ['$["answer"]'], certainty: "inferred", explanation: "Needs human review" },
              ] } },
            ] };
            if (!state.candidates.length) state.candidates.push({ candidate_id: "candidate-1", sample_id: "sample-1", generation_id: run.generation_id, status: "draft", mapping_digest: "mapping-digest", mapping_json: mapping });
          }
          if (run.status === "needs_manual_review") {
            run.error_code = "model_timeout";
            run.result_json = { reason: "model_timeout", attempts: [{ index: 0, outcome: "timeout", feedback: [{ code: "model_timeout" }] }] };
          }
          data = run;
        } else if (path.endsWith("/usage")) data = { job_count: 1, run_count: 1, artifact_count: 2, jobs: [{ job_id: "job-1", status: "completed" }], runs: [{ run_id: "run-1" }] };
        else if (path.endsWith("/versions")) data = state.versions;
        else if (/\/versions\/\d+$/.test(path)) data = state.versions[0];
      }
      assert.notEqual(data, undefined, `Unhandled Fake Registry route: ${method} ${path}`);
      return route.fulfill({ status, contentType: "application/json", headers: { "Access-Control-Allow-Origin": "*" }, body: JSON.stringify(data) });
    });
  await page.goto(origin + "/adapter-studio");
  await page.getByLabel("Registry 凭据", { exact: true }).fill("studio-test-token");
  await page.getByRole("button", { name: "连接 Registry", exact: true }).click();
  return { context, page, state, consoleErrors };
}

/** @param page Browser. @param noGolden Drop independent semantic evidence. @returns Creates profile and uploads actual local file. */
async function importEvidence(page, noGolden = false) {
  await page.getByText("创建 Adapter Profile", { exact: true }).click();
  await page.getByLabel("配置名称", { exact: true }).fill("Browser Adapter");
  await page.getByLabel("Agent 说明", { exact: true }).fill("Heterogeneous fixture");
  await page.getByRole("button", { name: "创建 Profile", exact: true }).click();
  await page.getByRole("heading", { name: "Browser Adapter", exact: true }).waitFor();
  await page.getByLabel("样本 JSON 文件", { exact: true }).setInputFiles({ name: "agent.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ samples: [{ response: fixture.raw_response, golden: noGolden ? null : fixture.golden }] })) });
  await page.getByRole("button", { name: "检查并保存样本", exact: true }).click();
  await page.getByLabel('披露 $["answer"]', { exact: true }).waitFor();
}

/** @param page Browser. @returns Creates manual candidate to isolate review tests from polling. */
async function manualCandidate(page) {
  await page.getByText("人工创建 / 修正 MappingSpec", { exact: true }).click();
  await page.getByLabel("人工 MappingSpec JSON", { exact: true }).fill(JSON.stringify(fixture.repair_reply.mapping));
  await page.getByRole("button", { name: "创建人工候选", exact: true }).click();
  await page.getByRole("button", { name: "运行预览", exact: true }).waitFor();
}

/** @param page Browser. @returns Clicks explicit review acknowledgement within candidate panel. */
async function acknowledge(page) {
  await page.getByLabel("已核对 Raw / Normalized、关键语义和独立 Golden，确认当前证据", { exact: true }).check();
}

test("complete upload → disclosure → asynchronous repair → preview → human review → publish → usage loop",
  /** @returns Exercises real DOM, terminal polling, immutable references and explicit publication. */
  async () => {
    const { context, page, state, consoleErrors } = await setup();
    try {
      await importEvidence(page);
      assert.equal(await page.getByRole("button", { name: "触发 AI Mapping Generation" }).isEnabled(), false);
      await page.getByLabel('披露 $["answer"]', { exact: true }).check();
      await page.getByRole("button", { name: "触发 AI Mapping Generation" }).click();
      await page.getByRole("button", { name: "打开生成候选" }).waitFor({ timeout: 15000 });
      const reads = state.generationReads;
      await page.waitForTimeout(2300);
      assert.equal(state.generationReads, reads, "terminal state stops polling");
      const command = state.commands.find(
        /** @param row Posted command. @returns Generation request. */ row => row.path.endsWith("/generations"));
      assert.deepEqual(command.body.request.disclosed_paths, ['$["answer"]']);
      assert.deepEqual(command.body.request.disclosed_values, []);
      assert.equal("samples" in command.body.request, false);
      assert.equal("golden" in command.body.request, false);
      await page.getByText("结构化错误 / 修复反馈", { exact: true }).first().click();
      await page.getByText("golden_value_mismatch", { exact: false }).first().waitFor();
      await page.getByText("Needs human review", { exact: false }).waitFor();
      await page.getByRole("button", { name: "打开生成候选" }).click();
      await page.getByRole("button", { name: "运行预览", exact: true }).click();
      await page.getByText("逐事件关联（raw_pointer / raw_event / normalized_event）", { exact: true }).click();
      await page.getByText('"/events/0"', { exact: false }).first().waitFor();
      assert.equal(state.commands.some(
        /** @param row Posted command. @returns Unexpected auto-publication. */ row => row.path.endsWith("/publish")), false);
      await page.getByRole("button", { name: "运行服务端验证", exact: true }).click();
      await page.getByText("验证允许进入人工审核；尚未发布。", { exact: true }).waitFor();
      await page.getByLabel("人工审核说明", { exact: true }).fill("Reviewed raw events and independent Golden");
      await acknowledge(page);
      await page.getByRole("button", { name: "审核通过", exact: true }).click();
      await page.getByText("发布将冻结新版本。", { exact: false }).waitFor();
      assert.equal(await page.getByRole("button", { name: "发布不可变 Mapping Version" }).isEnabled(), false);
      await acknowledge(page);
      await page.getByRole("button", { name: "发布不可变 Mapping Version" }).click();
      await page.getByText("已发布 v1。请在版本历史中查看。", { exact: true }).waitFor();
      await page.getByRole("button", { name: "v1", exact: true }).click();
      await page.getByText("绑定 Job：1；已保存 Run：1；Attempt 产物：2", { exact: true }).waitFor();
      assert.equal(await page.getByRole("link", { name: "run-1 · Replay Timeline", exact: true }).getAttribute("href"), "/runs/run-1/timeline");
      const review = state.commands.find(/** @param row Command. @returns Review. */ row => row.path.endsWith("/review"));
      assert.equal(review.body.validation_id, "validation-1");
      assert.equal(review.body.evidence_digest, "e".repeat(64));
      assert.equal(state.commands.filter(/** @param row Command. @returns Publish. */ row => row.path.endsWith("/publish")).length, 1);
      await page.getByRole("button", { name: "断开并清除本页凭据" }).click();
      await page.getByRole("button", { name: "连接 Registry", exact: true }).waitFor();
      assert.equal(await page.getByLabel("Registry 凭据", { exact: true }).inputValue(), "");
      assert.equal((await page.locator("body").innerText()).includes("SECRET-DO-NOT-SEND"), false);
      const storage = await page.evaluate(/** @returns Browser storage content; must not contain the credential. */
        () => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage }, url: location.href }));
      assert.equal(storage.includes("studio-test-token"), false);
      assert.deepEqual(consoleErrors, []);
    } finally { await context.close(); }
  });

test("no Golden stays unverified and cannot be reviewed or published",
  /** @returns Exercises semantic blockers even after note and acknowledgement. */
  async () => {
    const { context, page, state, consoleErrors } = await setup({ noGolden: true });
    try {
      await importEvidence(page, true); await manualCandidate(page);
      await page.getByRole("button", { name: "运行服务端验证", exact: true }).click();
      await page.getByText("golden_required", { exact: false }).waitFor();
      await page.getByLabel("人工审核说明", { exact: true }).fill("Cannot override Golden");
      await acknowledge(page);
      assert.equal(await page.getByRole("button", { name: "审核通过", exact: true }).isEnabled(), false);
      assert.equal(await page.getByRole("button", { name: "发布不可变 Mapping Version" }).isEnabled(), false);
      assert.equal(state.commands.some(/** @param row Command. @returns Unauthorized semantic override. */
        row => row.path.endsWith("/review") || row.path.endsWith("/publish")), false);
      assert.deepEqual(consoleErrors, []);
    } finally { await context.close(); }
  });

test("backend 403 review failure remains visible and never enables publication",
  /** @returns Confirms client UI cannot turn an editor into a publisher. */
  async () => {
    const { context, page, state, consoleErrors } = await setup({ forbidden: true });
    try {
      await importEvidence(page); await manualCandidate(page);
      await page.getByRole("button", { name: "运行服务端验证", exact: true }).click();
      await page.getByText("验证允许进入人工审核；尚未发布。", { exact: true }).waitFor();
      await page.getByLabel("人工审核说明", { exact: true }).fill("Editor cannot approve");
      await acknowledge(page); await page.getByRole("button", { name: "审核通过", exact: true }).click();
      await page.getByRole("alert").filter({ hasText: "adapter_forbidden" }).waitFor();
      assert.equal(await page.getByRole("button", { name: "发布不可变 Mapping Version" }).isEnabled(), false);
      assert.equal(state.versions.length, 0); assert.deepEqual(consoleErrors, []);
    } finally { await context.close(); }
  });

test("invalid credentials show 401 without retry and can be cleared",
  /** @returns Checks credential failure recovery without caching token/browser persistence. */
  async () => {
    const { context, page, state, consoleErrors } = await setup({ unauthorized: true });
    try {
      await page.getByRole("alert").filter({ hasText: "adapter_authentication_required" }).waitFor();
      const reads = state.requests.length;
      await page.waitForTimeout(2300);
      assert.equal(state.requests.length, reads, "no automatic retry after 401 (StrictMode may remount initial read)");
      await page.getByRole("button", { name: "断开并清除本页凭据" }).click();
      await page.getByLabel("Registry 凭据", { exact: true }).waitFor();
      assert.deepEqual(consoleErrors, []);
    } finally { await context.close(); }
  });

test("generation network failure pauses polling; explicit refresh recovers to needs_manual_review",
  /** @returns Checks HTTP failure recovery and durable terminal failure without automatic paid regeneration. */
  async () => {
    const { context, page, state, consoleErrors } = await setup({ generationNetworkFailure: true, generationFailure: true });
    try {
      await importEvidence(page);
      await page.getByLabel('披露 $["answer"]', { exact: true }).check();
      await page.getByRole("button", { name: "触发 AI Mapping Generation" }).click();
      await page.getByRole("alert").filter({ hasText: "Unable to connect" }).waitFor();
      const reads = state.requests.length;
      await page.waitForTimeout(2300);
      assert.equal(state.requests.length, reads, "network failure does not poll or retry");
      state.networkRecovered = true;
      await page.getByRole("button", { name: "刷新生成状态", exact: true }).click();
      await page.getByText("需要人工处理。", { exact: false }).waitFor({ timeout: 15000 });
      const terminalReads = state.generationReads;
      await page.waitForTimeout(2300);
      assert.equal(state.generationReads, terminalReads);
      assert.equal(state.commands.filter(
        /** @param row Command. @returns Paid generation enqueue. */ row => row.path.endsWith("/generations")).length, 1);
      assert.equal(state.versions.length, 0);
      assert.deepEqual(consoleErrors, []);
    } finally { await context.close(); }
  });

test("existing Evaluation Jobs navigation stays independent and returning Studio requires reconnect",
  /** @returns Checks route compatibility and disposal of private session on ordinary navigation. */
  async () => {
    const { context, page, state, consoleErrors } = await setup();
    try {
      await page.route("**/evaluation-jobs?*",
        /** @param route Existing unauthenticated jobs API. @returns Minimal empty legacy page. */
        route => route.fulfill({ contentType: "application/json", headers: { "Access-Control-Allow-Origin": "*" },
          body: JSON.stringify({ items: [], total: 0, limit: 20, offset: 0 }) }));
      await page.getByRole("link", { name: "Evaluation Jobs", exact: true }).click();
      await page.getByRole("heading", { name: "Evaluation Jobs", exact: true }).waitFor();
      await page.getByText("No jobs found for this status and page.", { exact: true }).waitFor();
      const reads = state.requests.length;
      await page.waitForTimeout(2300);
      assert.equal(state.requests.length, reads);
      await page.getByRole("link", { name: "Adapter Studio", exact: true }).click();
      await page.getByLabel("Registry 凭据", { exact: true }).waitFor();
      assert.equal(await page.getByLabel("Registry 凭据", { exact: true }).inputValue(), "");
      assert.deepEqual(consoleErrors, []);
    } finally { await context.close(); }
  });
