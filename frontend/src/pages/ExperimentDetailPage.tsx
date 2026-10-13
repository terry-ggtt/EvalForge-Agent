import { formatJobTime } from "../utils/evaluationJobs";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { getExperiment } from "../api/experiments";
import { JobError, JobSummary } from "../components/jobs/JobComponents";

/** @returns Persisted experiment and its actual run IDs, reusing existing run detail/timeline routes. */
export function ExperimentDetailPage() {
  const { experimentId = "" } = useParams<{ experimentId: string }>();
  const query = useQuery({
    queryKey: ["experiments", "detail", experimentId],
    /** @param context Query cancellation signal. @returns The selected experiment, not a limited list lookup. */
    queryFn: ({ signal }) => getExperiment(experimentId, signal),
    enabled: Boolean(experimentId),
    /** @param current Experiment snapshot. @returns Poll until execution finishes. */
    refetchInterval: (current) => current.state.data?.status === "running" ? 5_000 : false,
  });
  const experiment = query.data;
  return <div className="space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <Link to="/experiments" className="text-sm text-slate-500 hover:underline">← Experiments</Link>
      <button disabled={query.isFetching} type="button" onClick={
        /** @returns Refreshes experiment and run membership. */
        () => { void query.refetch(); }
      } className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm disabled:opacity-50">Refresh</button>
    </div>
    {query.isPending && <p role="status" className="text-sm text-slate-500">Loading experiment…</p>}
    {query.isError && <JobError error={query.error} />}
    {experiment && <>
      <div><h2 className="break-all text-2xl font-semibold">{experiment.name}</h2>
        <p className="mt-1 break-all text-sm text-slate-500">{experiment.experiment_id}</p></div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <JobSummary label="Status">{experiment.status}</JobSummary>
        <JobSummary label="Dataset Version">{experiment.dataset_version}</JobSummary>
        <JobSummary label="Agent Version">{experiment.agent_version}</JobSummary>
        <JobSummary label="Model">{experiment.model_name ?? "—"}</JobSummary>
        <JobSummary label="Prompt Version">{experiment.prompt_version ?? "—"}</JobSummary>
        <JobSummary label="Created">{formatJobTime(experiment.created_at)}</JobSummary>
        <JobSummary label="Completed">{formatJobTime(experiment.completed_at)}</JobSummary>
      </div>
      <section className="rounded-xl border border-slate-200 bg-white p-6">
        <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">Experiment Runs ({experiment.run_ids.length})</h3><Link to="/runs" className="text-sm text-blue-700 hover:underline">All Runs</Link></div>
        <p className="mt-2 text-sm text-slate-500">These run IDs belong to this experiment. Open a run for metrics or its existing trace timeline.</p>
        <ul className="mt-4 divide-y divide-slate-100">{experiment.run_ids.map(
          /** @param runId Actual persisted membership. @returns Links to existing result and trace viewers. */
          (runId) => <li key={runId} className="flex flex-wrap justify-between gap-3 py-3 text-sm">
            <Link className="break-all font-medium hover:underline" to={`/runs/${encodeURIComponent(runId)}`}>{runId}</Link>
            <Link className="text-blue-700 hover:underline" to={`/runs/${encodeURIComponent(runId)}/timeline`}>View Timeline</Link>
          </li>,
        )}</ul>
        {experiment.run_ids.length === 0 && <p className="py-6 text-sm text-slate-500">No persisted runs are available yet.</p>}
      </section>
    </>}
  </div>;
}
