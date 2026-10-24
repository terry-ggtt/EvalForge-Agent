import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { registryId } from "../../api/adapterStudio";
import { useRegistryCommand, useRegistryQuery } from "../../hooks/useAdapterStudio";
import { generationRequest, MAX_SAMPLE_BYTES, parseStudioJson, sampleUpload } from "../../utils/adapterStudio";
import type { Candidate, Generation, SampleBatch } from "../../types/adapterStudio";
import { JsonView, ReadState, studioButton, studioInput, StudioPanel } from "./StudioComponents";

/** @param props Profile and success selection. @returns JSON import with optional independent Golden evidence. */
export function SampleImport({ token, profileId, onSample }: {
  token: string; profileId: string; onSample: (id: string) => void;
}) {
  const [text, setText] = useState('{"samples":[{"response":null,"golden":null}]}');
  const [error, setError] = useState<unknown>(null);
  const upload = useRegistryCommand<SampleBatch>(token, `/profiles/${registryId(profileId)}/samples`,
    /** @param row Persisted batch. @returns Selects inspected evidence. */ row => onSample(row.sample_id));

  /** @param event Selected local file. @returns Reads bounded UTF-8 JSON locally; does not upload automatically. */
  async function readFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      if (file.size > MAX_SAMPLE_BYTES) throw new Error("文件超过 1.9 MB 限制。");
      const value = await file.text();
      parseStudioJson(value); setText(value); setError(null);
    } catch (failure) { setError(failure); }
  }
  /** @param event Explicit upload form event. @returns Sends parsed evidence; local/server failures remain visible. */
  function submit(event: FormEvent) {
    event.preventDefault(); setError(null);
    try { upload.mutate(sampleUpload(text)); } catch (failure) { setError(failure); }
  }
  return <StudioPanel title="2. 导入 Agent JSON 样本">
    <p className="text-sm text-slate-600">输入或上传本地样本批次。response 为原始响应；独立 Trace 用 trace + has_separate_trace: true。
      golden 可选，但发布需要人工独立编写的期望输出；不得复制预览结果冒充 Golden。</p>
    <form onSubmit={submit} className="space-y-3">
      <label className="block text-sm">上传 JSON 文件（仅本地读取）<input aria-label="样本 JSON 文件" type="file" accept=".json,application/json"
        className="mt-1 block" onChange={readFile} disabled={upload.isPending} /></label>
      <label className="block text-sm">样本批次 JSON<textarea aria-label="样本批次 JSON" rows={8} className={studioInput} value={text}
        onChange={/** @param event Edited JSON. @returns Updates local draft only. */ event => setText(event.target.value)} /></label>
      <button className={studioButton} disabled={upload.isPending}>{upload.isPending ? "检查并保存中…" : "检查并保存样本"}</button>
    </form>
    <ReadState pending={false} error={error ?? upload.error} />
    <JsonView label="样本与独立 Golden 格式说明" data={{
      samples: [{ response: { answer: "人工样本答案", events: [] }, partial_trace: false,
        golden: { name: "人工独立期望", output_text: "人工样本答案", spans: [], not_applicable: ["span_type", "token_usage", "tool_call"] } }],
    }} />
  </StudioPanel>;
}

/** @param props Immutable sample ID and new-task/candidate selection. @returns Inspector/disclosure/generation/manual candidate entry. */
export function SampleWorkspace({ token, profileId, sampleId, onGeneration, onCandidate }: {
  token: string; profileId: string; sampleId: string;
  onGeneration: (id: string) => void; onCandidate: (id: string) => void;
}) {
  const query = useRegistryQuery<SampleBatch>(token, `/samples/${registryId(sampleId)}`);
  return <StudioPanel title="3. Schema Inspector 与规则生成">
    <ReadState pending={query.isPending} error={query.error} />
    {query.data && <GenerationForm token={token} profileId={profileId} batch={query.data}
      onGeneration={onGeneration} onCandidate={onCandidate} />}
  </StudioPanel>;
}

/** @param props Actual server inspection and immutable sample binding. @returns Explicit opt-in model disclosure and manual fallback. */
function GenerationForm({ token, profileId, batch, onGeneration, onCandidate }: {
  token: string; profileId: string; batch: SampleBatch;
  onGeneration: (id: string) => void; onCandidate: (id: string) => void;
}) {
  const [paths, setPaths] = useState<string[]>([]);
  const [values, setValues] = useState("[]");
  const [hints, setHints] = useState("[]");
  const [approvedValues, setApprovedValues] = useState(false);
  const [mappingText, setMappingText] = useState("");
  const [error, setError] = useState<unknown>(null);
  const generate = useRegistryCommand<Generation>(token, `/profiles/${registryId(profileId)}/generations`,
    /** @param row Queued generation. @returns Selects its durable status. */ row => onGeneration(row.generation_id));
  const manual = useRegistryCommand<Candidate>(token, `/profiles/${registryId(profileId)}/candidates`,
    /** @param row New immutable manual candidate. @returns Selects review workspace. */ row => onCandidate(row.candidate_id));

  /** @returns Builds reviewed allowlists and queues once; errors never dispatch a generation. */
  function start() {
    setError(null);
    try {
      const request = generationRequest(batch.inspection_json, paths, values, hints);
      if (request.disclosed_values.length && !approvedValues) throw new Error("请先确认已检查并同意披露指定标量。");
      generate.mutate({ sample_id: batch.sample_id, request });
    } catch (failure) { setError(failure); }
  }
  /** @returns Creates a fresh manual DSL candidate; strict validation belongs to the backend. */
  function createManual() {
    setError(null);
    try { manual.mutate({ sample_id: batch.sample_id, mapping: parseStudioJson(mappingText) }); }
    catch (failure) { setError(failure); }
  }
  return <div className="space-y-4">
    <p className="break-all text-xs">样本：{batch.sample_id}<br />Schema Fingerprint：{batch.schema_fingerprint}</p>
    <JsonView label="本地验证样本 / Raw Trace / 独立 Golden（敏感）" data={batch.samples_json} />
    <p className="text-sm">勾选允许模型看到的字段名（默认不披露值，最多 256 项）。未知字段和敏感字段请保留未选。</p>
    <div className="max-h-80 overflow-auto">
      <table className="w-full text-left text-xs"><thead><tr><th>披露字段</th><th>类型</th><th>频率 / nullable / 缺失次数</th></tr></thead>
        <tbody>{batch.inspection_json.fields.map(
          /** @param field Inspector path summary. @returns One explicitly opt-in disclosure control. */
          field => <tr key={field.path} className="border-t border-slate-100">
            <td className="break-all p-2"><label><input type="checkbox" checked={paths.includes(field.path)}
              aria-label={`披露 ${field.path}`}
              onChange={/** @param event Disclosure decision. @returns Updates the selected allowlist only. */
                event => setPaths(event.target.checked ? [...paths, field.path] : paths.filter(
                  /** @param path Selected path. @returns Keeps other selections. */ path => path !== field.path))} /> {field.path}</label></td>
            <td className="p-2">{field.types.join(" | ")}</td>
            <td className="p-2">{(field.sample_frequency * 100).toFixed(0)}% / {String(field.nullable)} / {field.missing_occurrences}</td>
          </tr>)}</tbody></table>
    </div>
    <JsonView label="跨样本字段差异" data={batch.inspection_json.differences} />
    <details className="space-y-3"><summary className="cursor-pointer text-sm">必要标量披露和字段说明（可选）</summary>
      <p className="text-sm">事件类别等必要标量需单独授权。请展开原始样本核对真实值，再填写定位符，例如
        { ' [{"sample_index":0,"source":"response","path":"$.events[0].kind"}]' }。路径必须属于已选字段；不会自动披露整个样本。</p>
      <label className="block text-sm">授权标量定位符 JSON<textarea className={studioInput} rows={3} value={values}
        onChange={/** @param event Changed locators. @returns Invalidates prior value disclosure confirmation. */
          event => { setValues(event.target.value); setApprovedValues(false); }} /></label>
      <label className="block text-sm"><input type="checkbox" checked={approvedValues}
        onChange={/** @param event Explicit human consent. @returns Stores this local disclosure decision. */
          event => setApprovedValues(event.target.checked)} /> 已核对原始值并同意向模型披露这些标量</label>
      <label className="block text-sm">字段说明 JSON（source_path、description、optional）<textarea className={studioInput} rows={3} value={hints}
        onChange={/** @param event Edited hints. @returns Updates optional descriptions. */ event => setHints(event.target.value)} /></label>
    </details>
    <p className="text-xs text-slate-500">生成使用服务端预算和目标 AgentResult / TraceEvent；不会连接 Agent 或改变其 HTTP 配置。任务由 Registry Worker 异步处理。</p>
    <button type="button" className={studioButton} disabled={generate.isPending || !paths.length} onClick={start}>
      {generate.isPending ? "排队中…" : "触发 AI Mapping Generation"}</button>
    <details className="space-y-3"><summary className="cursor-pointer text-sm">人工创建 / 修正 MappingSpec</summary>
      <p className="text-sm">粘贴完整 MappingSpec，创建新候选。不会覆盖旧候选或已发布版本。</p>
      <textarea aria-label="人工 MappingSpec JSON" rows={8} className={studioInput} value={mappingText}
        onChange={/** @param event Edited DSL. @returns Updates local draft. */ event => setMappingText(event.target.value)} />
      <button type="button" className={studioButton} disabled={manual.isPending || !mappingText.trim()} onClick={createManual}>创建人工候选</button>
    </details>
    <ReadState pending={false} error={error ?? generate.error ?? manual.error} />
  </div>;
}
