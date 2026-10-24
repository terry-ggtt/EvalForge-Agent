import { useState } from "react";
import { Link } from "react-router";
import { registryId } from "../../api/adapterStudio";
import { useRegistryCommand, useRegistryQuery } from "../../hooks/useAdapterStudio";
import { canReview } from "../../utils/adapterStudio";
import type { Candidate, Generation, MappingResult, PublishedVersion, SampleBatch, ValidationRecord, Usage } from "../../types/adapterStudio";
import { JsonView, MappingTable, ReadState, RegistryList, studioButton, studioInput, studioSecondary, StudioPanel, ValidationView } from "./StudioComponents";

/** @param props Durable task and candidate navigation. @returns Bounded repair/status history; no LLM call during reads. */
export function GenerationPanel({ token, generationId, onCandidate }: {
  token: string; generationId: string; onCandidate: (id: string) => void;
}) {
  const query = useRegistryQuery<Generation>(token, `/generations/${registryId(generationId)}`, true);
  const run = query.data;
  return <StudioPanel title="4. 生成状态与修复记录">
    <ReadState pending={query.isPending} error={query.error} />
    <button type="button" className={studioSecondary} disabled={query.isFetching}
      onClick={/** @returns Re-reads persisted task, including after network failure. */ () => { void query.refetch(); }}>刷新生成状态</button>
    {run && <div className="space-y-3">
      <p role="status">状态：{run.status} · {run.result_json?.reason ?? run.error_code ?? "等待 Worker 处理"}</p>
      <p className="text-xs">模型调用：{run.calls_started}；预留 Token：{run.reserved_tokens}；费用预留上限：{run.reserved_cost_nano_usd} nano-USD（非实际账单）</p>
      {run.status === "needs_manual_review" && <p className="text-amber-800">需要人工处理。不会自动重新生成或发布；如要再次调用模型，请在样本页明确创建新任务。</p>}
      {run.result_json?.attempts.map(
        /** @param attempt Persisted bounded attempt. @returns Outcome, machine feedback and model-claimed evidence. */
        attempt => <div key={attempt.index} className="space-y-2 rounded-lg border border-slate-200 p-3 text-sm">
          <p>尝试 {attempt.index + 1}：{attempt.outcome}</p>
          <JsonView label="结构化错误 / 修复反馈" data={attempt.feedback} />
          <ul className="ml-5 list-disc">{attempt.proposal?.evidence.map(
            /** @param evidence Claimed source provenance. @param index Evidence order. @returns Explicit certainty, never semantic approval. */
            (evidence, index) => <li className={evidence.certainty === "observed" ? "" : "text-amber-800"} key={index}>
              {evidence.source_paths.join(", ")} → {evidence.target} · {evidence.event_source_type ?? "response"} · {evidence.certainty}
              {evidence.certainty !== "observed" ? " · 需人工核对" : " · 模型证据声明，仍需 Golden"}<br />{evidence.explanation}
            </li>)}</ul>
        </div>)}
      <JsonView label="持久化调用检查点（敏感，含模型回复）" data={run.checkpoints_json} />
      {run.candidate_id && <button type="button" className={studioButton}
        onClick={/** @returns Opens exact produced candidate; does not approve it. */ () => onCandidate(run.candidate_id!)}>打开生成候选</button>}
    </div>}
  </StudioPanel>;
}

/** @param props Selected candidate and profile. @returns Exact evidence, mapping preview and review workflow. */
export function CandidatePanel({ token, profileId, candidateId }: {
  token: string; profileId: string; candidateId: string;
}) {
  const query = useRegistryQuery<Candidate>(token, `/candidates/${registryId(candidateId)}`);
  return <StudioPanel title="5. Mapping / Trace 预览 / 验证 / 人工审核">
    <ReadState pending={query.isPending} error={query.error} />
    {query.data && <CandidateReview token={token} profileId={profileId} candidate={query.data} />}
  </StudioPanel>;
}

/** @param props Immutable candidate snapshot. @returns Raw/normalized evidence and separate explicit validate/review/publish actions. */
function CandidateReview({ token, profileId, candidate }: { token: string; profileId: string; candidate: Candidate }) {
  const base = `/candidates/${registryId(candidate.candidate_id)}`;
  const [validationId, setValidationId] = useState("");
  const [reviewId, setReviewId] = useState("");
  const [note, setNote] = useState("");
  const [checked, setChecked] = useState(false);
  const batch = useRegistryQuery<SampleBatch>(token, `/samples/${registryId(candidate.sample_id)}`);
  const latest = useRegistryQuery<{ validation_id: string }[]>(token, `${base}/validations?limit=1&offset=0`);
  const activeId = validationId || latest.data?.[0]?.validation_id || "";
  const validation = useRegistryQuery<ValidationRecord>(token, activeId ? `/validations/${registryId(activeId)}` : "");
  const audit = useRegistryQuery<{ audit_id: string; candidate_id: string; validation_id: string; action: string; details_json: unknown }[]>(
    token, candidate.status === "approved" ? `/profiles/${registryId(profileId)}/audit?limit=50&offset=0` : "");
  const existingApproval = audit.data?.find(
    /** @param row Authoritative audit record. @returns Only this candidate/report's explicit approval. */
    row => row.candidate_id === candidate.candidate_id && row.validation_id === activeId && row.action === "review_approved");
  const approvalId = reviewId || existingApproval?.audit_id || "";
  const preview = useRegistryCommand<{ mapping_results: MappingResult[] }>(token, `${base}/preview`);
  const validate = useRegistryCommand<ValidationRecord>(token, `${base}/validate`,
    /** @param row Fresh server report. @returns Resets approval confirmation and selects exact report. */
    row => { setValidationId(row.validation_id); setReviewId(""); setChecked(false); });
  const review = useRegistryCommand<{ audit_id: string; action: string }>(token, `${base}/review`,
    /** @param row Explicit persisted review. @returns Retains approval ID only when approved. */
    row => { setReviewId(row.action === "review_approved" ? row.audit_id : ""); setChecked(false); });
  const publish = useRegistryCommand<PublishedVersion>(token, `${base}/publish`);
  const busy = preview.isPending || validate.isPending || review.isPending || publish.isPending;
  const eligible = Boolean(validation.data?.eligible) && activeId === latest.data?.[0]?.validation_id;
  const allowReview = canReview(candidate.status, eligible, note) && checked && !busy;

  /** @param decision Explicit human decision. @returns Posts exact validation/digest, never a client-supplied report. */
  function submitReview(decision: "approve" | "reject") {
    if (!validation.data || !allowReview) return;
    review.mutate({ validation_id: validation.data.validation_id, evidence_digest: validation.data.evidence_digest, decision, note });
  }
  return <div className="space-y-4">
    <p className="break-all text-sm">{candidate.candidate_id} · {candidate.status}<br />Mapping Digest：{candidate.mapping_digest}</p>
    <MappingTable mapping={candidate.mapping_json} />
    <JsonView label="完整 MappingSpec（包括 enum_map 等操作参数）" data={candidate.mapping_json} />
    <div className="flex flex-wrap gap-3">
      <button type="button" className={studioButton} disabled={busy}
        onClick={/** @returns Requests deterministic preview only. */ () => preview.mutate({})}>运行预览</button>
      <button type="button" className={studioButton} disabled={busy || !["draft", "validated"].includes(candidate.status)}
        onClick={/** @returns Requests fresh server validation. */ () => validate.mutate({})}>运行服务端验证</button>
    </div>
    <ReadState pending={batch.isPending} error={batch.error} />
    {preview.data?.mapping_results.map(
      /** @param result Actual Runtime result. @param index Immutable sample order. @returns Paired whole roots and precise event provenance. */
      (result, index) => <div key={index} className="space-y-2 rounded-lg border border-slate-200 p-3">
        <p className="text-sm">样本 {index + 1} · Mapping {result.success ? "成功" : "失败"}</p>
        <div className="grid gap-3 lg:grid-cols-2">
          <JsonView label="Raw Response / Raw Trace / Golden（敏感）" data={batch.data?.samples_json[index]} />
          <JsonView label="Normalized Result / Trace" data={result.result} />
        </div>
        <JsonView label="逐事件关联（raw_pointer / raw_event / normalized_event）" data={result.events} />
        <JsonView label="Mapping 错误和警告" data={{ errors: result.errors, warnings: result.warnings }} />
      </div>)}
    <h4 className="text-sm font-semibold">验证报告历史</h4>
    <RegistryList token={token} path={`${base}/validations`} idKey="validation_id" selected={activeId}
      onSelect={/** @param id Chosen report. @returns Clears prior approval/confirmation before reading different evidence. */
        id => { setValidationId(id); setReviewId(""); setChecked(false); }} />
    <ReadState pending={Boolean(activeId) && validation.isPending} error={latest.error ?? validation.error} />
    {validation.data && <ValidationView record={validation.data} />}
    <p className="text-sm text-slate-600">Unverified 需要补充独立样本 / Golden 或修正规则后重新验证；勾选确认不会解除服务端阻断。审核只接受最新有效报告。</p>
    <label className="block text-sm">人工审核说明<textarea aria-label="人工审核说明" className={studioInput} rows={3}
      value={note} maxLength={2000} onChange={/** @param event Human note. @returns Updates audit explanation. */ event => setNote(event.target.value)} /></label>
    <label className="block text-sm"><input type="checkbox" checked={checked}
      onChange={/** @param event Human verification. @returns Records local acknowledgement only. */ event => setChecked(event.target.checked)} />
      已核对 Raw / Normalized、关键语义和独立 Golden，确认当前证据</label>
    <div className="flex flex-wrap gap-3">
      <button type="button" className={studioButton} disabled={!allowReview}
        onClick={/** @returns Explicit human approval command. */ () => submitReview("approve")}>审核通过</button>
      <button type="button" className={studioSecondary} disabled={!allowReview}
        onClick={/** @returns Explicit human rejection command. */ () => submitReview("reject")}>审核拒绝</button>
    </div>
    {candidate.status === "approved" && <div className="space-y-2">
      <ReadState pending={audit.isPending} error={audit.error} />
      <JsonView label="已有审核记录（重新进入后可恢复，最近 50 条）" data={existingApproval ?? null} />
      <label className="block text-sm">审核记录 ID（旧记录不在最近 50 条时填写）<input className={studioInput} value={approvalId}
        onChange={/** @param event Explicit prior approval reference. @returns Sets ID for server revalidation. */ event => setReviewId(event.target.value)} /></label>
      <p className="text-xs">发布将冻结新版本。请再次勾选上方确认；服务端会重新校验权限、审核及证据。</p>
    </div>}
    <button type="button" className={studioButton} disabled={busy || candidate.status !== "approved" || !approvalId || !checked}
      onClick={/** @returns Explicit independent publish command; server enforces transaction and authorization. */
        () => publish.mutate({ review_id: approvalId })}>发布不可变 Mapping Version</button>
    {publish.data && <p role="status" className="text-green-700">已发布 v{publish.data.version}。请在版本历史中查看。</p>}
    <ReadState pending={busy} error={preview.error ?? validate.error ?? review.error ?? publish.error} />
  </div>;
}

/** @param props Exact published version. @returns Immutable snapshot and real paginated job/run usage. */
export function VersionPanel({ token, profileId, version }: { token: string; profileId: string; version: string }) {
  const [offset, setOffset] = useState(0);
  const base = `/profiles/${registryId(profileId)}/versions/${registryId(version)}`;
  const query = useRegistryQuery<PublishedVersion>(token, base);
  const usage = useRegistryQuery<Usage>(token, `${base}/usage?limit=10&offset=${offset}`);
  return <StudioPanel title={`历史版本 v${version} 与使用情况`}>
    <ReadState pending={query.isPending} error={query.error} />
    {query.data && <>
      <p className="break-all text-xs">发布人：{query.data.published_by} · {query.data.published_at}<br />
        Schema：{query.data.schema_fingerprint}<br />Mapping：{query.data.mapping_digest}</p>
      <MappingTable mapping={query.data.mapping_json} />
      <JsonView label="不可变发布快照与审核证据 ID" data={query.data} />
    </>}
    <ReadState pending={usage.isPending} error={usage.error} />
    {usage.data && <div className="space-y-2 text-sm">
      <p>绑定 Job：{usage.data.job_count}；已保存 Run：{usage.data.run_count}；Attempt 产物：{usage.data.artifact_count}</p>
      <p className="text-xs">绑定数包含未执行和失败的 Job；Run 仅统计已持久化产物，各列表独立分页。</p>
      <div className="flex flex-col gap-2">{usage.data.jobs.map(
        /** @param job Referencing job. @returns Existing job-detail navigation. */
        job => <Link className="text-blue-700 underline" key={job.job_id} to={`/evaluation-jobs/${registryId(job.job_id)}`}>{job.job_id} · {job.status}</Link>)}
        {usage.data.runs.map(
          /** @param run Persisted normalized run. @returns Existing replay navigation. */
          run => <Link className="text-blue-700 underline" key={run.run_id} to={`/runs/${registryId(run.run_id)}/timeline`}>{run.run_id} · Replay Timeline</Link>)}</div>
      <div className="flex gap-3">
        <button type="button" className={studioSecondary} disabled={!offset}
          onClick={/** @returns Previous usage page. */ () => setOffset(Math.max(0, offset - 10))}>上一页使用记录</button>
        <button type="button" className={studioSecondary} disabled={offset + 10 >= Math.max(usage.data.job_count, usage.data.run_count)}
          onClick={/** @returns Next usage page. */ () => setOffset(offset + 10)}>下一页使用记录</button>
      </div>
    </div>}
  </StudioPanel>;
}
