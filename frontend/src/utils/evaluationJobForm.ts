import type { ExperimentTestCase, ExpectedToolCall } from "../types/api";
import type { CreateEvaluationJobRequest } from "../types/evaluationJobs";

export interface CaseDraft {
  key: string;
  id: string;
  input_text: string;
  expected_output: string;
  toolCalls: string;
  metadata: string;
}
export interface JobDraft {
  name: string;
  dataset_version: string;
  agent_version: string;
  model_name: string;
  prompt_version: string;
  metadata: string;
  cases: CaseDraft[];
}

/** @param value Parsed JSON. @returns True for JSON objects, excluding arrays and null. */
function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** @param text User JSON. @param label Field name. @returns Valid object. @throws Error with the field's validation problem. */
function parseObject(text: string, label: string): Record<string, unknown> {
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw new Error(`${label} must contain valid JSON.`); }
  if (!isObject(value)) throw new Error(`${label} must be a JSON object.`);
  return value;
}

/** @param text User tool call JSON. @param label Case context. @returns Backend tool-call array or null. @throws Error for unsupported structures. */
function parseToolCalls(text: string, label: string): ExpectedToolCall[] | null {
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw new Error(`${label}: expected tool calls must contain valid JSON.`); }
  if (value === null) return null;
  if (!Array.isArray(value)) throw new Error(`${label}: expected tool calls must be an array or null.`);
  return value.map(
    /** @param call Untrusted JSON call. @param index Position for validation errors. @returns Canonical expected call. */
    (call: unknown, index: number) => {
      if (!isObject(call) || typeof call.tool_name !== "string" || call.tool_name.length === 0) {
        throw new Error(`${label}: tool call ${index + 1} requires a nonempty tool_name.`);
      }
      const args = call.arguments === undefined ? {} : call.arguments;
      if (!isObject(args)) throw new Error(`${label}: tool call arguments must be a JSON object.`);
      return { tool_name: call.tool_name, arguments: args };
    },
  );
}

/** @param draft Form fields with editable JSON. @returns Backend-compatible creation request. @throws Error before network submission on invalid fields. */
export function buildEvaluationJobRequest(draft: JobDraft): CreateEvaluationJobRequest {
  const name = draft.name.trim();
  const dataset = draft.dataset_version.trim();
  const agent = draft.agent_version.trim();
  if (!name || !dataset || !agent) throw new Error("Name, dataset version and agent version are required.");
  if (!draft.cases.length) throw new Error("At least one case is required.");
  const ids = new Set<string>();
  const cases: ExperimentTestCase[] = draft.cases.map(
    /** @param item Editable case. @param index Case index. @returns Validated case without trimming semantic input/output. */
    (item, index) => {
      const label = `Case ${index + 1}`;
      if (!item.id.trim() || item.id !== item.id.trim()) throw new Error(`${label}: case ID must be nonblank without surrounding whitespace.`);
      if (ids.has(item.id)) throw new Error(`Duplicate case ID: ${item.id}`);
      ids.add(item.id);
      if (typeof item.input_text !== "string" || item.input_text.length < 1) throw new Error(`${label}: input must be a nonempty string.`);
      if (typeof item.expected_output !== "string") throw new Error(`${label}: expected output must be a string.`);
      return {
        id: item.id, input_text: item.input_text, expected_output: item.expected_output,
        expected_tool_calls: parseToolCalls(item.toolCalls, label),
        metadata: parseObject(item.metadata, `${label} metadata`),
      };
    },
  );
  return {
    name, dataset_version: dataset, agent_version: agent,
    model_name: draft.model_name.trim() || null,
    prompt_version: draft.prompt_version.trim() || null,
    metadata: parseObject(draft.metadata, "Job metadata"), cases,
  };
}

/** @returns Blank case with a stable editing key, never a fabricated execution result. */
export function newCaseDraft(): CaseDraft {
  return { key: crypto.randomUUID(), id: "", input_text: "", expected_output: "", toolCalls: "null", metadata: "{}" };
}
