import { formatJobTime } from "../utils/evaluationJobs";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { cancelEvaluationJob, evaluationJobKeys } from "../api/evaluationJobs";
import { JobError, JobProgress, JobStatusBadge, JobSummary } from "../components/jobs/JobComponents";
import { useEvaluationJob } from "../hooks/useEvaluationJob";
import type { EvaluationJobSnapshot } from "../hooks/useEvaluationJob";
import { canCancelJob } from "../utils/evaluationJobs";

/** @returns Job detail, true progress, cooperative cancellation and existing result navigation. */
export function EvaluationJobDetailPage() {
  const { jobId = "" } = useParams<{ jobId: string }>();
  const client = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const mutation = useMutation({
    /** @returns Persisted cancel response for this route's job. */
    mutationFn: () => cancelEvaluationJob(jobId),
    /** @returns Aborts in-flight detail reads before submitting a cancellation. */
    onMutate: async () => { await client.cancelQueries({ queryKey: evaluationJobKeys.detail(jobId) }); },
    /** @param job Actual API response. @returns Updates cache without inventing a terminal state. */
    onSuccess: async (job) => {
      await client.cancelQueries({ queryKey: evaluationJobKeys.detail(jobId) });
      client.setQueryData<EvaluationJobSnapshot>(evaluationJobKeys.detail(jobId), {
        job, progress: null, progressError: null,
      });
      setConfirming(false);
      void client.invalidateQueries({ queryKey: evaluationJobKeys.lists });
      void client.invalidateQueries({ queryKey: evaluationJobKeys.detail(jobId) });
    },
  });
  const query = useEvaluationJob(jobId, !mutation.isPending);
  const snapshot = query.data;
  if (!snapshot) return <div className="space-y-4">
    <Link to="/evaluation-jobs" className="text-sm text-slate-500 hover:underline">← Evaluation Jobs</Link>
    {query.isError ? <JobError error={query.error} /> : <p role="status">Loading evaluation job…</p>}
    <button type="button" onClick={
      /** @returns Retries failed detail loading. */
      () => { void query.refetch(); }
    } className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm">Retry</button>
  </div>;

  const { job, progress } = snapshot;
  // Separate HTTP responses can straddle a transition. Never mix mismatching counters or states.
  const matchingProgress = progress?.status === job.status
    && progress.completed_cases === job.completed_cases
    && progress.failed_cases === job.failed_cases
    && progress.started_at === job.started_at
    && progress.finished_at === job.finished_at ? progress : null;
  const processed = job.completed_cases + job.failed_cases;

  return <div className="space-y-6">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><Link to="/evaluation-jobs" className="text-sm text-slate-500 hover:underline">← Evaluation Jobs</Link>
        <h2 className="mt-2 break-all text-2xl font-semibold">{job.name}</h2>
        <p className="mt-1 break-all text-sm text-slate-500">{job.job_id}</p></div>
      <div className="flex flex-wrap items-center gap-3">
        <JobStatusBadge status={job.status} />
        <button type="button" disabled={query.isFetching || mutation.isPending} onClick={
          /** @returns Refreshes detail and progress from the server. */
          () => { void query.refetch(); }
        } className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm disabled:opacity-50">{query.isFetching ? "Refreshing…" : "Refresh"}</button>
        {canCancelJob(job.status) && <button type="button" disabled={mutation.isPending} onClick={
          /** @returns Opens an inline accessible confirmation and clears any earlier mutation error. */
          () => { mutation.reset(); setConfirming(true); }
        } className="rounded-lg border border-red-300 bg-white px-4 py-2 text-sm text-red-700 disabled:opacity-50">Cancel Job</button>}
      </div>
    </div>
    {query.isError && <JobError error={query.error} />}
    {snapshot.progressError != null && <div className="space-y-2"><p className="text-sm text-slate-500">Progress endpoint unavailable; displaying the last job detail snapshot.</p><JobError error={snapshot.progressError} /></div>}
    {mutation.isError && <JobError error={mutation.error} />}
    {confirming && canCancelJob(job.status) && <section aria-labelledby="cancel-heading" className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-5">
      <h3 id="cancel-heading" className="font-semibold">Cancel this evaluation?</h3>
      <p className="text-sm">Queued jobs can be cancelled immediately. Running jobs wait for the worker to acknowledge cancellation. Completed case results remain available.</p>
      <div className="flex flex-wrap gap-3">
        <button autoFocus type="button" disabled={mutation.isPending} onClick={
          /** @returns Closes confirmation without a server mutation. */
          () => setConfirming(false)
        } className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm">Keep Job</button>
        <button type="button" disabled={mutation.isPending} onClick={
          /** @returns Submits at most one cancellation mutation while pending. */
          () => { if (!mutation.isPending) mutation.mutate(); }
        } className="rounded-lg bg-red-700 px-4 py-2 text-sm text-white disabled:opacity-50">{mutation.isPending ? "Requesting…" : "Confirm Cancellation"}</button>
      </div>
    </section>}
    {job.status === "cancel_requested" && <p role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">Cancellation requested. Waiting for the worker; the job is still active.</p>}
    {job.status === "queued" && job.attempt_count > 0 && <p className="text-sm text-slate-600">This job is queued again after an earlier worker attempt. Worker and progress below reflect the current server state.</p>}
    {job.failed_cases > 0 && <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">{job.failed_cases} case(s) failed. Failed cases count toward processed progress; review available runs for errors.</p>}
    <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-6">
      <h3 className="font-semibold">Execution Progress</h3>
      <JobProgress percent={job.progress_percent} processed={processed} total={job.total_cases} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <JobSummary label="Total Cases">{job.total_cases}</JobSummary>
        <JobSummary label="Completed Cases">{job.completed_cases}</JobSummary>
        <JobSummary label="Failed Cases">{job.failed_cases}</JobSummary>
        <JobSummary label="Processed Cases">{processed}</JobSummary>
        <JobSummary label="Remaining Cases">{job.total_cases - processed}</JobSummary>
        <JobSummary label="Elapsed Time">{matchingProgress?.elapsed_seconds != null ? `${matchingProgress.elapsed_seconds.toFixed(1)} s` : "—"}</JobSummary>
      </div>
    </section>
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <JobSummary label="Dataset Version">{job.dataset_version}</JobSummary>
      <JobSummary label="Agent Version">{job.agent_version}</JobSummary>
      <JobSummary label="Worker ID">{job.worker_id ?? "Unassigned"}</JobSummary>
      <JobSummary label="Worker Execution Attempts">{job.attempt_count}<p className="mt-1 text-xs font-normal text-slate-500">Worker attempts, not case retries.</p></JobSummary>
      <JobSummary label="Created">{formatJobTime(job.created_at)}</JobSummary>
      <JobSummary label="Started">{formatJobTime(job.started_at)}</JobSummary>
      <JobSummary label="Finished">{formatJobTime(job.finished_at)}</JobSummary>
      <JobSummary label="Updated">{formatJobTime(job.updated_at)}</JobSummary>
      <JobSummary label="Experiment ID">{job.experiment_id ?? "Not assigned yet"}</JobSummary>
    </div>
    {(job.error || job.status === "failed") && <section className="rounded-xl border border-red-200 bg-red-50 p-5 text-red-700">
      <h3 className="font-semibold">Job Error</h3><p className="mt-2 whitespace-pre-wrap break-words text-sm">{job.error ?? "Job failed without an error message. Inspect available results and worker logs."}</p>
    </section>}
    <section className="rounded-xl border border-slate-200 bg-white p-6">
      <h3 className="font-semibold">Evaluation Results</h3>
      {job.experiment_id ? <Link to={`/experiments/${encodeURIComponent(job.experiment_id)}`} className="mt-3 inline-block rounded-lg bg-slate-900 px-4 py-2 text-sm text-white">View Experiment &amp; Runs</Link>
        : <p className="mt-2 text-sm text-slate-500">No experiment is available yet. A job cancelled before execution may have no results.</p>}
    </section>
  </div>;
}
