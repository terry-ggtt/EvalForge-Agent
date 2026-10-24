import type { Inspection, Json, MappingSpec, ValidationSample } from "../types/adapterStudio.ts";

export const MAX_SAMPLE_BYTES = 1_900_000;

/** @param text Imported JSON text. @returns Parsed bounded JSON; throws readable syntax/size errors.
 * The backend remains authoritative for contracts, limits, paths and Golden validation.
 */
export function parseStudioJson(text: string): Json {
  if (new TextEncoder().encode(text).length > MAX_SAMPLE_BYTES) throw new Error("JSON 超过前端 1.9 MB 限制。");
  try { return JSON.parse(text) as Json; }
  catch { throw new Error("JSON 格式错误，请检查引号、逗号和括号。"); }
}

/** @param text Human-authored ValidationSample batch. @returns Immutable upload body or local shape error.
 * No conversion from preview into Golden; nullable response and separate trace are preserved.
 */
export function sampleUpload(text: string): { samples: ValidationSample[] } {
  const value = parseStudioJson(text);
  if (!value || Array.isArray(value) || typeof value !== "object" || !Array.isArray(value.samples)
    || value.samples.length < 1 || value.samples.length > 16) throw new Error("请提供 { samples: [...] }，包含 1～16 个样本。");
  for (const sample of value.samples) {
    if (!sample || Array.isArray(sample) || typeof sample !== "object" || !Object.hasOwn(sample, "response")) {
      throw new Error("每个样本必须显式包含 response；独立 Trace 需设置 has_separate_trace。");
    }
  }
  return value as unknown as { samples: ValidationSample[] };
}

/** @param inspection Server-inspected snapshot. @param paths Explicit selected field names.
 * @param valuesText Independently approved scalar locators. @param hintsText Optional field descriptions.
 * @returns Generation request without raw samples, Golden or client-selected budget.
 * Throws on invalid selection; server validates scalar locators against stored evidence.
 */
export function generationRequest(inspection: Inspection, paths: string[], valuesText: string, hintsText: string) {
  const available = new Set(inspection.fields.map(
    /** @param field Inspector field. @returns Its normalized disclosure path. */ field => field.path));
  if (!paths.length || paths.length > 256 || new Set(paths).size !== paths.length || paths.some(
    /** @param path Selected path. @returns Whether it is outside current sample. */ path => !available.has(path))) {
    throw new Error("请明确选择 1～256 个当前样本字段。");
  }
  const values = parseStudioJson(valuesText), hints = parseStudioJson(hintsText);
  if (!Array.isArray(values) || !Array.isArray(hints)) throw new Error("标量授权与字段说明必须为 JSON 数组。");
  if (values.length > 32 || hints.length > 128) throw new Error("标量最多 32 项，说明最多 128 项。");
  return { inspection, disclosed_paths: [...paths], disclosed_values: values, field_hints: hints };
}

/** @param status Durable generation status. @returns Poll only queued/running; errors are handled by query. */
export function generationIsActive(status: string): boolean {
  return status === "queued" || status === "running";
}

/** @param spec Actual candidate/published DSL. @returns Response/event-scoped source → target table rows. */
export function mappingRows(spec: MappingSpec) {
  const rows = spec.response.fields.map(
    /** @param field Response declaration. @returns Scoped visible mapping. */
    field => ({ scope: "response", ...field }));
  for (const rule of spec.trace?.rules ?? []) {
    for (const field of rule.fields) rows.push({ scope: `${rule.source_type} → ${rule.event_type}`, ...field });
  }
  return rows;
}

/** @param candidateStatus Current server candidate. @param eligible Server report release decision.
 * @param note Human review explanation. @returns Whether explicit review can be offered; never authorizes server access.
 */
export function canReview(candidateStatus: string, eligible: boolean, note: string): boolean {
  return candidateStatus === "validated" && eligible && note.trim().length > 0;
}
