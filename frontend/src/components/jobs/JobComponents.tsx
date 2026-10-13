import type { ReactNode } from "react";
import { ApiClientError } from "../../api/client";
import type { EvaluationJobStatus } from "../../types/evaluationJobs";
import { jobStatusLabel } from "../../utils/evaluationJobs";

/** @param props Server state. @returns Consistent color and explicit status text. */
export function JobStatusBadge({ status }: { status: EvaluationJobStatus }) {
  const colors: Record<EvaluationJobStatus, string> = {
    queued: "bg-slate-100 text-slate-700", running: "bg-blue-50 text-blue-700",
    cancel_requested: "bg-amber-50 text-amber-800", completed: "bg-green-50 text-green-700",
    failed: "bg-red-50 text-red-700", cancelled: "bg-slate-100 text-slate-600",
  };
  return <span className={`inline-flex whitespace-nowrap rounded-full px-3 py-1 text-xs font-medium ${colors[status]}`}>{jobStatusLabel(status)}</span>;
}

/** @param props Server percentage and counts. @returns Accessible real progress; failures count as processed. */
export function JobProgress({ percent, processed, total }: { percent: number; processed: number; total: number }) {
  return <div className="min-w-32 space-y-1">
    <div className="flex justify-between gap-3 text-xs text-slate-600">
      <span>{processed} / {total}</span><span>{percent.toFixed(1)}%</span>
    </div>
    <progress aria-label="Processed cases" max={100} value={percent} className="h-2 w-full accent-slate-900" />
  </div>;
}

/** @param props Label and actual value. @returns Responsive summary card. */
export function JobSummary({ label, children }: { label: string; children: ReactNode }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-5">
    <p className="text-sm text-slate-500">{label}</p>
    <div className="mt-2 break-all font-semibold">{children}</div>
  </div>;
}

/** @param props Existing client or network error. @returns Accessible error with useful 404/network distinction. */
export function JobError({ error }: { error: unknown }) {
  const message = error instanceof ApiClientError && error.status === 404
    ? "This resource does not exist or is no longer available."
    : error instanceof TypeError
      ? "Unable to connect to the API. Check the backend connection and try again."
      : error instanceof Error ? error.message : "Request failed. Please try again.";
  return <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{message}</div>;
}

