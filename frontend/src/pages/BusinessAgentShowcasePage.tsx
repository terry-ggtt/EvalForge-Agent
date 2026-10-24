import { useMutation, useQueries, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router";
import { apiRequest } from "../api/client";
import { createEvaluationJob } from "../api/evaluationJobs";
import { getExperiment } from "../api/experiments";
import { getRun } from "../api/runs";
import { JobError, JobStatusBadge } from "../components/jobs/JobComponents";
import { useEvaluationJob } from "../hooks/useEvaluationJob";
import type { CreateEvaluationJobRequest } from "../types/evaluationJobs";
import type { RunDetail } from "../types/api";

interface ShowcaseCase {
  id: string; title: string; input_text: string; expected_output: string;
  baseline_profile: string; candidate_profile: string; baseline_fault?: string;
  evaluation: Record<string, unknown>; explanation: string;
}
interface Showcase {
  version: string; title: string; scope: string; adapter: string;
  corpus_sha256: string; chunks: number; cases: ShowcaseCase[];
}

/** @param jobId Persisted job ID. @returns Actual job, experiment membership and existing Run resources. */
function useShowcaseResults(jobId: string) {
  const job = useEvaluationJob(jobId);
  const experimentId = job.data?.job.experiment_id ?? "";
  const experiment = useQuery({
    queryKey: ["experiments", "detail", experimentId],
    /** @param context Abort signal. @returns Selected actual experiment. */
    queryFn: ({ signal }) => getExperiment(experimentId, signal),
    enabled: Boolean(experimentId),
    /** @param current Snapshot. @returns Poll for growing run membership while the job is active. */
    refetchInterval: (current) => current.state.data?.status === "running" ? 2_000 : false,
  });
  const runs = useQueries({
    queries: (experiment.data?.run_ids ?? []).map(
      /** @param id Persisted run identity. @returns Existing Run query definition. */
      (id) => ({
        queryKey: ["run", id],
        /** @returns Existing Run Detail resource; no independent result store. */
        queryFn: () => getRun(id),
      }),
    ),
  });
  return { job, experiment, runs };
}

/** @param props Actual run or not-yet-executed state. @returns Quality/execution distinction and existing trace links. */
function ResultCell({ run }: { run?: RunDetail }) {
  if (!run) return <span className="text-slate-400">Waiting for result…</span>;
  const scored = run.result.metrics.filter(
    /** @param metric Applicable measured metric. @returns Whether it contributes to the displayed quality. */
    (metric) => metric.score !== null,
  );
  const imperfect = scored.some(
    /** @param metric Applicable metric. @returns Whether this explicit criterion was not fully met. */
    (metric) => (metric.score ?? 1) < 1,
  );
  return <div className="min-w-48 space-y-2">
    <p className={run.result.error ? "font-medium text-red-700" : imperfect ? "font-medium text-amber-800" : "font-medium text-green-700"}>
      {run.result.error ? "执行失败" : imperfect ? "执行完成 · 存在质量缺口" : "执行完成 · 当前判定项通过"}
    </p>
    {run.result.error ? <p className="max-w-xs break-words text-xs text-red-700">{run.result.error}</p>
      : <><p className="text-xs text-slate-500">综合质量分：{run.result.score.toFixed(3)}</p>
        <ul className="space-y-1 text-xs">{scored.map(
          /** @param metric Actual evaluation score. @returns Individual auditable objective. */
          (metric) => <li key={metric.name}>{metric.name}: <strong>{metric.score?.toFixed(3)}</strong></li>,
        )}</ul></>}
    <div className="flex flex-wrap gap-3 text-xs">
      <Link className="text-blue-700 hover:underline" to={`/runs/${encodeURIComponent(run.run_id)}`}>证据与指标</Link>
      <Link className="text-blue-700 hover:underline" to={`/runs/${encodeURIComponent(run.run_id)}/timeline`}>完整 Trace</Link>
    </div>
  </div>;
}

/** @returns Real paired Job creation and persisted, shareable failure/correction walkthrough. */
export function BusinessAgentShowcasePage() {
  const [search, setSearch] = useSearchParams();
  const definition = useQuery({
    queryKey: ["business-agent-showcase"],
    /** @returns Versioned synthetic cases and server-selected adapter mode. */
    queryFn: () => apiRequest<Showcase>("/showcase/business-agent"),
  });
  const hasPairInUrl = Boolean(search.get("baseline") || search.get("candidate"));
  const latest = useQuery({
    queryKey: ["business-agent-showcase-latest"],
    /** @returns Only an explicitly linked persisted pair; never matches by experiment names. */
    queryFn: () => apiRequest<{ baseline: string | null; candidate: string | null }>("/showcase/business-agent/latest"),
    enabled: !hasPairInUrl,
  });
  const baselineId = search.get("baseline") ?? (!hasPairInUrl ? latest.data?.baseline ?? "" : "");
  const candidateId = search.get("candidate") ?? (!hasPairInUrl ? latest.data?.candidate ?? "" : "");
  const baseline = useShowcaseResults(baselineId);
  const candidate = useShowcaseResults(candidateId);
  const mutation = useMutation({
    /** @param resumeCandidate Preserve an accepted baseline after a candidate creation failure. @returns Actual accepted job pair. */
    mutationFn: async (resumeCandidate: boolean) => {
      const data = definition.data;
      if (!data || data.adapter !== "business_http") throw new Error("请先按接入文档为 API 与 Worker 启用 business_http。");
      /** @param variant Compared configuration. @returns Real creation payload with fixed identical labels. */
      function request(variant: "baseline" | "candidate"): CreateEvaluationJobRequest {
        return {
          name: `面试演示 · ${variant === "baseline" ? "诊断基线" : "修正方案"} · ${new Date().toLocaleString()}`,
          dataset_version: data!.version, agent_version: `business-agent-v0.4/${variant}`,
          metadata: { showcase: "business-agent", variant, baseline_job_id: variant === "candidate" ? acceptedBaseline : null, corpus_sha256: data!.corpus_sha256 },
          cases: data!.cases.map(
            /** @param item Fixed question/reference. @returns Actual case with only declared profile/fault controls. */
            (item) => ({
              id: item.id, input_text: item.input_text, expected_output: item.expected_output,
              expected_tool_calls: null,
              metadata: {
                evaluation: item.evaluation, corpus_sha256: data!.corpus_sha256,
                retrieval_profile: variant === "baseline" ? item.baseline_profile : item.candidate_profile,
                fault_injection: variant === "baseline" ? item.baseline_fault ?? "none" : "none",
                scenario_title: item.title, showcase: "business-agent",
              },
            }),
          ),
        };
      }
      let acceptedBaseline = resumeCandidate ? baselineId : "";
      if (!acceptedBaseline) {
        const job = await createEvaluationJob(request("baseline"));
        acceptedBaseline = job.job_id;
        setSearch({ baseline: acceptedBaseline });
      }
      const job = await createEvaluationJob(request("candidate"));
      setSearch({ baseline: acceptedBaseline, candidate: job.job_id });
      return { baseline: acceptedBaseline, candidate: job.job_id };
    },
  });
  const data = definition.data;
  const baselineRuns = baseline.runs.flatMap(
    /** @param query Existing run result. @returns Successfully loaded run only. */
    (query) => query.data ? [query.data] : [],
  );
  const candidateRuns = candidate.runs.flatMap(
    /** @param query Existing run result. @returns Successfully loaded run only. */
    (query) => query.data ? [query.data] : [],
  );
  const errors: unknown[] = [
    definition.error, latest.error, mutation.error, baseline.job.error, candidate.job.error,
    baseline.experiment.error, candidate.experiment.error,
    ...baseline.runs.map(
      /** @param query Run query. @returns Its actual error, if any. */
      (query) => query.error,
    ),
    ...candidate.runs.map(
      /** @param query Run query. @returns Its actual error, if any. */
      (query) => query.error,
    ),
  ].filter(Boolean);
  return <div className="space-y-6">
    <div className="flex flex-wrap justify-between gap-4">
      <div><h2 className="text-2xl font-semibold">Agent 接入与 RAG 诊断演示</h2>
        <p className="mt-2 text-sm text-slate-500">真实 Agent → 原有 Job Queue / Worker → 引用与质量评测 → Run / Trace。</p></div>
      <button type="button" disabled={!data || data.adapter !== "business_http" || mutation.isPending} onClick={
        /** @returns Creates a new real baseline/candidate pair; no mock execution. */
        () => mutation.mutate(false)
      } className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50">{mutation.isPending ? "正在创建任务…" : "创建一组真实评测"}</button>
    </div>
    {errors.map(
      /** @param error Query/mutation error. @param index Stable position for displayed error. @returns Existing client error presentation. */
      (error, index) => <JobError key={index} error={error} />,
    )}
    {definition.isPending && <p role="status">Loading scenarios…</p>}
    {data && <>
      <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-6 text-sm">
        <h3 className="font-semibold">演示边界与判定规则</h3>
        <p>{data.scope}</p>
        <p>语料：{data.chunks} 个真实文件片段。Baseline 每行展示具体配置；候选方案使用 Hybrid + RRF + BGE 重排 + 显式证据门控。质量缺口与运行异常分开显示。</p>
        <p>门控是固定 logit ≥ 0 的演示策略，未经生产校准。拒答判定要求空检索、空引用和明确拒答；模型已安全拒答但仍召回无关材料，也不会通过该联合判定。引用分数是来源 ID 与标注匹配，不代表语义蕴含证明。这里只调用隔离的只读业务工具，不批准写入。</p>
        <p>Dense 故障注入单独标注，修正表示移除注入并重新执行；不宣称自动自愈。运行会调用本地 CPU 模型及 Agent 已配置的在线回答模型。</p>
        {data.adapter !== "business_http" && <p className="font-medium text-amber-800">当前后端 adapter 为 {data.adapter}；请先启用 business_http，避免误将 DemoAgent 当成真实接入。</p>}
        {baselineId && !candidateId && <button disabled={mutation.isPending} type="button" onClick={
          /** @returns Resumes only the missing candidate creation, retaining the accepted baseline. */
          () => mutation.mutate(true)
        } className="rounded-lg border border-slate-300 px-3 py-2 disabled:opacity-50">保留基线，仅补建 Candidate</button>}
      </section>
      <div className="grid gap-4 sm:grid-cols-2">{[
        ["Baseline · 诊断基线", baselineId, baseline.job.data?.job],
        ["Candidate · 修正方案", candidateId, candidate.job.data?.job],
      ].map(
        /** @param tuple Comparison side identity and actual server job. @returns Existing Job/Experiment links. */
        ([label, id, job]) => <section key={String(label)} className="space-y-3 rounded-xl border border-slate-200 bg-white p-5">
          <h3 className="font-semibold">{String(label)}</h3>
          {job && typeof job === "object" && "status" in job && <JobStatusBadge status={job.status} />}
          {typeof id === "string" && id && <Link className="block break-all text-sm text-blue-700 hover:underline" to={`/evaluation-jobs/${encodeURIComponent(id)}`}>Job：{id}</Link>}
          {job && typeof job === "object" && "experiment_id" in job && job.experiment_id && <Link className="block text-sm text-blue-700 hover:underline" to={`/experiments/${encodeURIComponent(job.experiment_id)}`}>查看 Experiment 与 Runs</Link>}
        </section>,
      )}</div>
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-left text-sm"><thead className="border-b border-slate-200 bg-slate-50 text-slate-500"><tr>
          <th className="min-w-64 px-4 py-3">问题 / 判定依据</th><th className="px-4 py-3">Baseline</th><th className="px-4 py-3">Candidate</th>
        </tr></thead><tbody>{data.cases.map(
          /** @param item Identical reference case. @returns Actual before/after metrics and trace links. */
          (item) => <tr key={item.id} className="border-b border-slate-100 align-top last:border-0">
            <td className="max-w-md space-y-3 px-4 py-5"><h3 className="font-medium">{item.title}</h3><p>{item.input_text}</p>
              <p className="text-xs text-slate-500">{item.explanation}</p>
              <p className="text-xs text-slate-500">{item.baseline_profile} {item.baseline_fault ? "+ 故障注入" : ""} → {item.candidate_profile}</p></td>
            <td className="px-4 py-5"><ResultCell run={baselineRuns.find(
              /** @param run Actual baseline run. @returns Match by the stable case ID. */
              (run) => run.case.id === item.id,
            )} /></td>
            <td className="px-4 py-5"><ResultCell run={candidateRuns.find(
              /** @param run Actual candidate run. @returns Match by the identical case ID. */
              (run) => run.case.id === item.id,
            )} /></td>
          </tr>,
        )}</tbody></table>
      </div>
    </>}
  </div>;
}
