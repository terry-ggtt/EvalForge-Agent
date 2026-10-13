import assert from "node:assert/strict";
import { test } from "node:test";
import { buildEvaluationJobRequest } from "../src/utils/evaluationJobForm.ts";
import { canCancelJob, isTerminalJob, jobStatuses, jobStatusLabel } from "../src/utils/evaluationJobs.ts";

/** @returns Valid editable user data; mutating tests get a fresh independent draft. */
function validDraft() {
  return {
    name: " evaluation ", dataset_version: " v1 ", agent_version: " agent-v2 ",
    model_name: "", prompt_version: "", metadata: "{}",
    cases: [{ key: "editing-key", id: "case-1", input_text: "  input\n", expected_output: "",
      toolCalls: '[{"tool_name":"lookup","arguments":{"query":"RAG"}}]', metadata: '{"owner":"test"}' }],
  };
}

test("six states distinguish cancellation acknowledgement from a terminal state",
  /** @returns Verifies each state and cancel eligibility, including recovery to queued. */
  () => {
    assert.equal(jobStatuses.length, 6);
    for (const status of jobStatuses) {
      assert.equal(isTerminalJob(status), ["completed", "failed", "cancelled"].includes(status));
      assert.equal(canCancelJob(status), ["queued", "running"].includes(status));
      assert.ok(jobStatusLabel(status).length);
    }
    assert.equal(jobStatusLabel("cancel_requested"), "Cancel requested");
    assert.equal(isTerminalJob("cancel_requested"), false);
    assert.equal(canCancelJob("queued"), true);
  });

test("creation canonicalizes configuration while preserving semantic text and optional empty expected answer",
  /** @returns Checks exact field shape and backend defaults without fake agent choices. */
  () => {
    const request = buildEvaluationJobRequest(validDraft());
    assert.equal(request.name, "evaluation");
    assert.equal(request.dataset_version, "v1");
    assert.equal(request.agent_version, "agent-v2");
    assert.equal(request.model_name, null);
    assert.equal(request.cases[0].input_text, "  input\n");
    assert.equal(request.cases[0].expected_output, "");
    assert.deepEqual(request.cases[0].expected_tool_calls, [{ tool_name: "lookup", arguments: { query: "RAG" } }]);
    assert.deepEqual(request.cases[0].metadata, { owner: "test" });
    assert.equal("key" in request.cases[0], false);
  });

test("rejects blank configuration, empty dataset and invalid or duplicate case identifiers",
  /** @returns Verifies client rejection before any mutation. */
  () => {
    for (const field of ["name", "dataset_version", "agent_version"]) {
      const draft = validDraft(); draft[field] = " ";
      assert.throws(/** @returns Executes validation, which must reject this invalid draft. */ () => buildEvaluationJobRequest(draft), /required/);
    }
    const empty = validDraft(); empty.cases = [];
    assert.throws(/** @returns Executes validation, which must reject this invalid draft. */ () => buildEvaluationJobRequest(empty), /At least one/);
    for (const id of ["", " ", " case-1", "case-1 "]) {
      const draft = validDraft(); draft.cases[0].id = id;
      assert.throws(/** @returns Executes validation, which must reject this invalid draft. */ () => buildEvaluationJobRequest(draft), /case ID/);
    }
    const duplicate = validDraft(); duplicate.cases.push({ ...duplicate.cases[0], key: "another" });
    assert.throws(/** @returns Executes validation, which must reject this invalid draft. */ () => buildEvaluationJobRequest(duplicate), /Duplicate/);
  });

test("rejects invalid JSON structures and tool arguments without altering valid null/empty calls",
  /** @returns Exercises field-aware errors and canonical backend-compatible tool-call defaults. */
  () => {
    for (const text of ["{broken", "null", "[]", '"string"']) {
      const draft = validDraft(); draft.metadata = text;
      assert.throws(/** @returns Executes validation, which must reject this invalid draft. */ () => buildEvaluationJobRequest(draft), /Job metadata/);
      draft.metadata = "{}"; draft.cases[0].metadata = text;
      assert.throws(/** @returns Executes validation, which must reject this invalid draft. */ () => buildEvaluationJobRequest(draft), /Case 1 metadata/);
    }
    for (const text of ["{broken", "{}", "[{}]", '[{"tool_name":""}]', '[{"tool_name":"x","arguments":[]}]']) {
      const draft = validDraft(); draft.cases[0].toolCalls = text;
      assert.throws(/** @returns Executes validation, which must reject this invalid draft. */ () => buildEvaluationJobRequest(draft), /Case 1/);
    }
    for (const [text, result] of [["null", null], ["[]", []], ['[{"tool_name":"lookup"}]', [{ tool_name: "lookup", arguments: {} }]]]) {
      const draft = validDraft(); draft.cases[0].toolCalls = text;
      assert.deepEqual(buildEvaluationJobRequest(draft).cases[0].expected_tool_calls, result);
    }
    const draft = validDraft(); draft.cases[0].input_text = "";
    assert.throws(/** @returns Executes validation, which must reject this invalid draft. */ () => buildEvaluationJobRequest(draft), /nonempty string/);
  });
