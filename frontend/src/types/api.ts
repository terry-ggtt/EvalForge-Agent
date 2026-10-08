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