import type { ExperimentTestCase } from "./api";

export type EvaluationJobStatus =
  | "queued" | "running" | "cancel_requested"
  | "completed" | "failed" | "cancelled";

/** HTTP response from EvaluationJobResponse; worker attempts are not case retries. */
export interface EvaluationJob {
  job_id: string;
  status: EvaluationJobStatus;
  name: string;
  dataset_version: string;
  agent_version: string;
  experiment_id: string | null;
  total_cases: number;
  completed_cases: number;
  failed_cases: number;
  progress_percent: number;
  error: string | null;
  worker_id: string | null;
  attempt_count: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface EvaluationJobListResponse {
  items: EvaluationJob[];
  total: number;
  limit: number;
  offset: number;
}

export interface EvaluationJobProgressResponse {
  job_id: string;
  status: EvaluationJobStatus;
  total_cases: number;
  completed_cases: number;
  failed_cases: number;
  processed_cases: number;
  remaining_cases: number;
  progress_percent: number;
  is_terminal: boolean;
  experiment_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  elapsed_seconds: number | null;
}

export interface CreateEvaluationJobRequest {
  name: string;
  dataset_version: string;
  agent_version: string;
  model_name?: string | null;
  prompt_version?: string | null;
  metadata?: Record<string, unknown>;
  cases: ExperimentTestCase[];
}
