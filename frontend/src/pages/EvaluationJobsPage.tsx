import { formatJobTime } from "../utils/evaluationJobs";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { evaluationJobKeys, getEvaluationJobs } from "../api/evaluationJobs";
import { JobError, JobProgress, JobStatusBadge } from "../components/jobs/JobComponents";
import type { EvaluationJobStatus } from "../types/evaluationJobs";
import { isTerminalJob, jobStatuses, jobStatusLabel } from "../utils/evaluationJobs";

const PAGE_SIZE = 20;

/** @returns Server-paginated job management page; polling is scoped to this mounted query. */
export function EvaluationJobsPage() {
  const [status, setStatus] = useState<EvaluationJobStatus | "">("");
  const [offset, setOffset] = useState(0);
  const params = { status, limit: PAGE_SIZE, offset };
  const query = useQuery({
    queryKey: evaluationJobKeys.list(params),
    /** @param context Query abort signal. @returns Only this filter/page's server response. */
    queryFn: ({ signal }) => getEvaluationJobs(params, signal),
    /** @param current Query snapshot. @returns Poll only while a visible job is active. */
    refetchInterval: (current) => current.state.data?.items.some(
      /** @param job Visible job. @returns Whether it still needs updates. */
      (job) => !isTerminalJob(job.status),
    ) ? 5_000 : false,
  });
  const page = query.data;
  return <div className="space-y-6">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><h2 className="text-2xl font-semibold">Evaluation Jobs</h2>
        <p className="mt-1 text-sm text-slate-500">Create and monitor asynchronous evaluations.</p></div>
      <Link className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white" to="/evaluation-jobs/new">Create Job</Link>
    </div>
    <div className="flex flex-wrap items-end gap-4">
      <div className="space-y-2 text-sm font-medium"><label htmlFor="job-status" className="block">Status</label>
        <select id="job-status" value={status} onChange={
          /** @param event Status selection. @returns Nothing; atomically resets the page. */
          (event) => { setStatus(event.target.value as EvaluationJobStatus | ""); setOffset(0); }
        } className="block rounded-lg border border-slate-300 bg-white px-3 py-2">
          <option value="">All statuses</option>
          {jobStatuses.map(
            /** @param value Valid backend status. @returns Select option. */
            (value) => <option key={value} value={value}>{jobStatusLabel(value)}</option>,
          )}
        </select>
      </div>
      <button type="button" disabled={query.isFetching} onClick={
        /** @returns Starts one manual refresh of the current page. */
        () => { void query.refetch(); }
      } className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm disabled:opacity-50">{query.isFetching ? "Refreshing…" : "Refresh"}</button>
      <span className="text-sm text-slate-500" role="status">{page ? `${page.total} jobs` : "Loading jobs…"}</span>
    </div>
    {query.isError && <JobError error={query.error} />}
    {query.isPending && <p role="status" className="text-sm text-slate-500">Loading evaluation jobs…</p>}
    {page && <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 text-slate-500"><tr>
          {["Name / Job ID", "Status", "Progress", "Completed", "Failed", "Attempt", "Worker", "Created At", "Actions"].map(
            /** @param title Column name. @returns Table header. */
            (title) => <th key={title} className="whitespace-nowrap px-4 py-3">{title}</th>,
          )}
        </tr></thead>
        <tbody>{page.items.map(
          /** @param job Persisted job. @returns Row with real worker and counts. */
          (job) => <tr key={job.job_id} className="border-b border-slate-100 last:border-0">
            <td className="px-4 py-3"><Link className="font-medium hover:underline" to={`/evaluation-jobs/${encodeURIComponent(job.job_id)}`}>{job.name}</Link><p className="mt-1 break-all text-xs text-slate-500">{job.job_id}</p></td>
            <td className="px-4 py-3"><JobStatusBadge status={job.status} /></td>
            <td className="px-4 py-3"><JobProgress percent={job.progress_percent} processed={job.completed_cases + job.failed_cases} total={job.total_cases} /></td>
            <td className="px-4 py-3">{job.completed_cases}</td><td className="px-4 py-3">{job.failed_cases}</td>
            <td className="px-4 py-3">{job.attempt_count}</td><td className="px-4 py-3">{job.worker_id ?? "—"}</td>
            <td className="whitespace-nowrap px-4 py-3">{formatJobTime(job.created_at)}</td>
            <td className="px-4 py-3"><Link className="text-blue-700 hover:underline" aria-label={`View ${job.name}`} to={`/evaluation-jobs/${encodeURIComponent(job.job_id)}`}>View</Link></td>
          </tr>,
        )}</tbody>
      </table>
      {page.items.length === 0 && <p className="p-10 text-center text-sm text-slate-500">No jobs found for this status and page.</p>}
    </div>}
    <div className="flex items-center justify-between gap-3 text-sm">
      <button type="button" disabled={offset === 0 || query.isFetching} onClick={
        /** @returns Moves back one server page. */
        () => setOffset(Math.max(0, offset - PAGE_SIZE))
      } className="rounded-lg border border-slate-300 bg-white px-4 py-2 disabled:opacity-40">Previous</button>
      <span className="text-slate-500">{page ? `${page.items.length ? offset + 1 : 0}–${offset + page.items.length} of ${page.total}` : "Loading…"}</span>
      <button type="button" disabled={!page || offset + PAGE_SIZE >= page.total || query.isFetching} onClick={
        /** @returns Moves forward one server page. */
        () => setOffset(offset + PAGE_SIZE)
      } className="rounded-lg border border-slate-300 bg-white px-4 py-2 disabled:opacity-40">Next</button>
    </div>
  </div>;
}
