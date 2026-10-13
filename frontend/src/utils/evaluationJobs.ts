import type { EvaluationJobStatus } from "../types/evaluationJobs";

export const jobStatuses: readonly EvaluationJobStatus[] = [
  "queued", "running", "cancel_requested", "completed", "failed", "cancelled",
];

/** @param status Server job state. @returns True only for the three terminal states. */
export function isTerminalJob(status: EvaluationJobStatus): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}

/** @param status Server job state. @returns Whether a new cancel action is useful. */
export function canCancelJob(status: EvaluationJobStatus): boolean {
  return status === "queued" || status === "running";
}

/** @param status Job state. @returns Human-readable state without altering its semantics. */
export function jobStatusLabel(status: EvaluationJobStatus): string {
  const labels: Record<EvaluationJobStatus, string> = {
    queued: "Queued", running: "Running", cancel_requested: "Cancel requested",
    completed: "Completed", failed: "Failed", cancelled: "Cancelled",
  };
  return labels[status];
}

/** @param value ISO server timestamp or absent. @returns Localized timestamp or unavailable marker. */
export function formatJobTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}
