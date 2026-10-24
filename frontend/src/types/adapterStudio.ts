import type { TraceEvent } from "./api";

/** Registry JSON contracts; immutable snapshots mirror backend and reuse existing TraceEvent. */
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export interface Profile { profile_id: string; name: string; description: string; trace_profile_json: Json }
export interface SchemaField {
  path: string; types: string[]; sample_frequency: number; nullable: boolean;
  occurrences: number; missing_occurrences: number; sample_count: number;
}
export interface Inspection {
  schema_fingerprint: string; fields: SchemaField[]; differences: Json[];
  [key: string]: unknown;
}
export interface ValidationSample {
  response: Json; trace?: Json; has_separate_trace?: boolean;
  golden?: Json; partial_trace?: boolean;
}
export interface SampleBatch {
  sample_id: string; schema_fingerprint: string;
  samples_json: ValidationSample[]; inspection_json: Inspection;
}
export interface FieldMapping {
  target: string; operation: { op: string; path?: string; paths?: string[]; [key: string]: Json | undefined };
  value_type: string; on_missing: string; on_null: string;
}
export interface MappingSpec {
  spec_version: string; name: string; response: { fields: FieldMapping[] };
  trace?: { events_path: string; type_path: string; rules: { source_type: string; event_type: string; fields: FieldMapping[] }[] } | null;
}
export interface Candidate {
  candidate_id: string; sample_id: string; generation_id: string | null;
  status: string; mapping_digest: string; mapping_json: MappingSpec;
}
export interface Issue { code: string; message: string; path?: string | null; [key: string]: unknown }
export interface ValidationReport {
  l1: string; l2: string; l3: string; errors: Issue[]; warnings: Issue[]; unverified: Issue[];
  release_allowed: boolean; release_blockers: string[]; golden_fields_verified: string[];
}
export interface ValidationRecord {
  validation_id: string; eligible: boolean; evidence_digest: string; reports_json: ValidationReport[];
}
export interface MappingResult {
  success: boolean;
  result: { output_text: string; trace: TraceEvent[]; metadata: Record<string, unknown> } | null;
  errors: Issue[]; warnings: Issue[];
  events: { raw_pointer: string; raw_event: Json; normalized_event: TraceEvent | null; [key: string]: unknown }[];
}
export interface Evidence {
  event_source_type: string | null; target: string; source_paths: string[];
  certainty: string; explanation: string;
}
export interface Generation {
  generation_id: string; sample_id: string; status: string; candidate_id?: string | null;
  error_code: string | null; calls_started: number; checkpoints_json: Json[];
  reserved_tokens: number; reserved_cost_nano_usd: number;
  result_json: null | { reason: string; status: string; attempts: {
    index: number; outcome: string; feedback: { code: string; layer?: string }[];
    proposal?: { evidence: Evidence[] } | null;
  }[] };
}
export interface PublishedVersion {
  profile_id: string; version: number; candidate_id: string; validation_id: string;
  published_by: string; published_at: string; mapping_digest: string;
  schema_fingerprint: string; mapping_json: MappingSpec; snapshot_json: { sample_id: string };
}
export interface Usage {
  job_count: number; run_count: number; artifact_count: number;
  jobs: { job_id: string; status: string }[]; runs: { run_id: string }[];
}
export interface ListRow {
  profile_id?: string; name?: string; sample_id?: string; candidate_id?: string;
  generation_id?: string; validation_id?: string; version?: number;
  status?: string; eligible?: boolean; created_at?: string;
}
