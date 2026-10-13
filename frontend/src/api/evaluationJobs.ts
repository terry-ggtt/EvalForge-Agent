import { apiRequest } from "./client";
import type {
  CreateEvaluationJobRequest, EvaluationJob, EvaluationJobListResponse,
  EvaluationJobProgressResponse, EvaluationJobStatus,
} from "../types/evaluationJobs";

export interface GetEvaluationJobsParams {
  status?: EvaluationJobStatus | "";
  limit: number;
  offset: number;
}

export const evaluationJobKeys = {
  all: ["evaluation-jobs"] as const,
  lists: ["evaluation-jobs", "list"] as const,
  /** @param params Server filters/page. @returns Unique cache identity for this page. */
  list: (params: GetEvaluationJobsParams) => ["evaluation-jobs", "list", params] as const,
  /** @param jobId Job identifier. @returns Identity of the combined detail/progress snapshot. */
  detail: (jobId: string) => ["evaluation-jobs", "detail", jobId] as const,
};

/** @param request Validated payload. @returns Accepted persisted job; does not execute it. */
export function createEvaluationJob(request: CreateEvaluationJobRequest) {
  return apiRequest<EvaluationJob>("/evaluation-jobs", {
    method: "POST", body: JSON.stringify(request),
  });
}

/** @param params Status and server pagination. @param signal Query cancellation. @returns Server page. */
export function getEvaluationJobs(params: GetEvaluationJobsParams, signal?: AbortSignal) {
  const search = new URLSearchParams({
    limit: String(params.limit), offset: String(params.offset),
  });
  if (params.status) search.set("status", params.status);
  return apiRequest<EvaluationJobListResponse>(`/evaluation-jobs?${search}`, { signal });
}

/** @param jobId Opaque identifier. @param signal Query cancellation. @returns Job, or existing client error. */
export function getEvaluationJob(jobId: string, signal?: AbortSignal) {
  return apiRequest<EvaluationJob>(`/evaluation-jobs/${encodeURIComponent(jobId)}`, { signal });
}

/** @param jobId Opaque identifier. @param signal Query cancellation. @returns Server progress and elapsed time. */
export function getEvaluationJobProgress(jobId: string, signal?: AbortSignal) {
  return apiRequest<EvaluationJobProgressResponse>(
    `/evaluation-jobs/${encodeURIComponent(jobId)}/progress`, { signal },
  );
}

/** @param jobId Opaque identifier. @returns Actual cancellation state; may be cancel_requested. */
export function cancelEvaluationJob(jobId: string) {
  return apiRequest<EvaluationJob>(`/evaluation-jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
  });
}
