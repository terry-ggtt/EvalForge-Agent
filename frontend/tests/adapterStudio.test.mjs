import assert from "node:assert/strict";
import { test } from "node:test";
import { canReview, generationIsActive, generationRequest, mappingRows, MAX_SAMPLE_BYTES, parseStudioJson, sampleUpload } from "../src/utils/adapterStudio.ts";

test("sample import preserves explicit null, separate traces and independently entered Golden",
  /** @returns Checks contract shape and no implicit data/Golen fabrication. */
  () => {
    const sample = { response: null, trace: [], has_separate_trace: true, golden: { name: "human" }, partial_trace: true };
    const text = JSON.stringify({ samples: [sample] });
    assert.deepEqual(sampleUpload(text), { samples: [sample] });
    assert.equal(text, JSON.stringify({ samples: [sample] }));
    for (const invalid of ["{}", '{"samples":[]}', '{"samples":[{}]}', '{"samples":[null]}', "{broken"]) {
      assert.throws(/** @returns Parses invalid user input. */ () => sampleUpload(invalid));
    }
    assert.throws(/** @returns Exercises backend-aligned sample-count bound. */
      () => sampleUpload(JSON.stringify({ samples: Array(17).fill({ response: null }) })));
    assert.throws(/** @returns Checks byte limit for multibyte input. */
      () => parseStudioJson(JSON.stringify("中".repeat(MAX_SAMPLE_BYTES / 2))), /限制/);
  });

test("model disclosure is explicit, bounded, current-schema-only, and excludes Raw/Golden/budget",
  /** @returns Checks exact disclosure command and failure before HTTP mutation. */
  () => {
    const inspection = { fields: [{ path: "$" }, { path: '$["events"][]["kind"]' }], schema_fingerprint: "fp" };
    const values = '[{"sample_index":0,"source":"response","path":"$.events[0].kind"}]';
    const request = generationRequest(inspection, ['$["events"][]["kind"]'], values, "[]");
    assert.deepEqual(request.disclosed_paths, ['$["events"][]["kind"]']);
    assert.equal(request.disclosed_values[0].source, "response");
    assert.equal("samples" in request, false);
    assert.equal("golden" in request, false);
    assert.equal("budget" in request, false);
    for (const paths of [[], ["absent"], ["$", "$"], Array(257).fill("$")]) {
      assert.throws(/** @returns Builds disallowed disclosure. */ () => generationRequest(inspection, paths, "[]", "[]"));
    }
    for (const bad of ["null", "{}", "{bad"]) {
      assert.throws(/** @returns Checks arrays rather than implicit coercion. */ () => generationRequest(inspection, ["$"], bad, "[]"));
    }
    assert.throws(/** @returns Checks scalar-count cap. */
      () => generationRequest(inspection, ["$"], JSON.stringify(Array(33).fill({})), "[]"));
  });

test("source-target table retains event scope, declared operation and missing/null policy",
  /** @returns Verifies separate response/event contexts and no accidental transformation. */
  () => {
    const field = { target: "$.output_text", operation: { op: "extract", path: "$.answer" }, value_type: "string", on_missing: "error", on_null: "error" };
    const spec = { response: { fields: [field] }, trace: { rules: [{ source_type: "vendor", event_type: "llm_end", fields: [{ ...field, operation: { op: "sum_if_present", paths: ["$.in", "$.out"] } }] }] } };
    const before = JSON.stringify(spec);
    const rows = mappingRows(spec);
    assert.equal(rows[0].scope, "response");
    assert.equal(rows[1].scope, "vendor → llm_end");
    assert.deepEqual(rows[1].operation.paths, ["$.in", "$.out"]);
    assert.equal(rows[0].on_missing, "error");
    assert.equal(JSON.stringify(spec), before);
  });

test("terminal states stop polling; only eligible validated candidates with a human note can be reviewed",
  /** @returns Prevents automatic review for unverified semantics, drafts and historical states. */
  () => {
    for (const status of ["queued", "running"]) assert.equal(generationIsActive(status), true);
    for (const status of ["completed", "failed", "needs_manual_review", "unexpected"]) assert.equal(generationIsActive(status), false);
    assert.equal(canReview("validated", true, "Independent Golden reviewed"), true);
    for (const status of ["draft", "approved", "published", "rejected"]) assert.equal(canReview(status, true, "note"), false);
    assert.equal(canReview("validated", false, "note"), false);
    assert.equal(canReview("validated", true, " "), false);
  });
