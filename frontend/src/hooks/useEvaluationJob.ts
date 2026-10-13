import { ApiClientError } from "../api/client";
import { useQuery } from "@tanstack/react-query";
import { evaluationJobKeys, getEvaluationJob, getEvaluationJobProgress } from "../api/evaluationJobs";
import { isTerminalJob } from "../utils/evaluationJobs";
import type { EvaluationJob, EvaluationJobProgressResponse } from "../types/evaluationJobs";

export interface EvaluationJobSnapshot {
  job: EvaluationJob;
  progress: EvaluationJobProgressResponse | null;
  progressError: unknown;
}

/** @param jobId Selected job. @param enabled Pause reads during cancellation. @returns A polling server snapshot query. */
export function useEvaluationJob(jobId: string, enabled = true) {
  return useQuery({
    queryKey: evaluationJobKeys.detail(jobId),
    enabled: Boolean(jobId) && enabled,
    /** @param context Query abort signal. @returns Detail plus independently handled progress result. */
    queryFn: async ({ signal }): Promise<EvaluationJobSnapshot> => {
      const [detail, progress] = await Promise.allSettled([
        getEvaluationJob(jobId, signal), getEvaluationJobProgress(jobId, signal),
      ]);
      if (detail.status === "rejected") throw detail.reason;
      return {
        job: detail.value,
        progress: progress.status === "fulfilled" ? progress.value : null,
        progressError: progress.status === "rejected" ? progress.reason : null,
      };
    },
    /** @param current Most recent server snapshot. @returns Interval until a terminal state, never synthetic progress. */
    refetchInterval: (current) => {
      if (current.state.error instanceof ApiClientError && current.state.error.status >= 400 && current.state.error.status < 500) return false;
      return current.state.data && isTerminalJob(current.state.data.job.status) ? false : 2_000;
    },
  });
}
