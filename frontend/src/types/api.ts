export interface HealthResponse {
  status: string;
}
export type ExperimentStatus =
  | "running"
  | "completed"
  | "failed";


export interface Experiment {
  experiment_id: string;

  name: string;

  status: ExperimentStatus;

  dataset_version: string;

  agent_version: string;

  model_name: string | null;

  prompt_version: string | null;

  run_ids: string[];

  created_at: string;

  completed_at: string | null;

  metadata: Record<
    string,
    unknown
  >;
}


export interface ExperimentListResponse {
  items: Experiment[];

  count: number;
}

export interface ApiErrorPayload {
  code: string;

  message: string;

  details: unknown;
}


export interface ApiErrorResponse {
  error: ApiErrorPayload;
}

export interface ExpectedToolCall {
  tool_name: string;

  arguments: Record<
    string,
    unknown
  >;
}


export interface ExperimentTestCase {
  id: string;

  input_text: string;

  expected_output: string;

  expected_tool_calls:
    ExpectedToolCall[] | null;

  metadata: Record<
    string,
    unknown
  >;
}


export interface RunExperimentRequest {
  name: string;

  dataset_version: string;

  agent_version: string;

  model_name: string | null;

  prompt_version: string | null;

  metadata: Record<
    string,
    unknown
  >;

  cases: ExperimentTestCase[];
}


export type RunStatus =
  | "succeeded"
  | "failed"
  | "timed_out";


export interface RunSummary {
  run_id: string;

  case_id: string | null;

  status: RunStatus;

  score: number | null;

  error: string | null;

  started_at: string;

  completed_at: string;
}


export interface RunListResponse {
  items: RunSummary[];

  total: number;

  limit: number;

  offset: number;
}


export interface TraceEvent {
  type: string;

  timestamp: string;

  payload: Record<
    string,
    unknown
  >;
}


export interface MetricResult {
  name: string;

  value: number | null;

  unit: string | null;

  score: number | null;

  details: Record<
    string,
    unknown
  >;
}


export interface RunTestCase {
  id: string | null;

  input_text: string;

  expected_output: string;

  expected_tool_calls: unknown[];

  metadata: Record<
    string,
    unknown
  >;
}


export interface CaseResult {
  run_id: string | null;

  case_id: string | null;

  input_text: string;

  expected_output: string;

  actual_output: string | null;

  metrics: MetricResult[];

  score: number;

  trace: TraceEvent[];

  error: string | null;
}


export interface RunDetail {
  run_id: string;

  status: RunStatus;

  case: RunTestCase;

  result: CaseResult;

  started_at: string;

  completed_at: string;

  metadata: Record<
    string,
    unknown
  >;
}


export interface TimelineEvent {
  sequence: number;

  timestamp: string;

  relative_ms: number;

  delta_ms: number;

  event_type: string;

  attempt_id: string | null;

  payload: Record<
    string,
    unknown
  >;
}


export interface RunTimeline {
  run_id: string;

  case_id: string | null;

  status: RunStatus;

  started_at: string;

  completed_at: string;

  duration_ms: number;

  events: TimelineEvent[];
}