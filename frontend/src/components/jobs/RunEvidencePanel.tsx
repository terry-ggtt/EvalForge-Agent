import type { RunDetail } from "../../types/api";

/** @param props Existing persisted run. @returns Real retrieval source cards and auditable metric details. */
export function RunEvidencePanel({ run }: { run: RunDetail }) {
  const observed = run.result.trace.some(
    /** @param event Persisted observation. @returns Whether this came from the business Agent adapter. */
    (event) => {
      const metadata = event.payload.metadata;
      return metadata !== null && typeof metadata === "object"
        && "source" in metadata && metadata.source === "business-agent";
    },
  );
  if (!observed && !run.case.metadata.retrieval_profile) return null;
  const events = run.result.trace.filter(
    /** @param event Canonical observation. @returns Parent retrieval result events with source text. */
    (event) => event.type === "tool_result" && event.payload.tool_name === "knowledge.search",
  );
  const sources: Record<string, unknown>[] = events.flatMap(
    /** @param event Actual tool response. @returns Only valid source object payloads. */
    (event) => {
      const result = event.payload.result;
      if (!result || typeof result !== "object" || !("retrieved" in result) || !Array.isArray(result.retrieved)) return [];
      return result.retrieved.filter(
        /** @param source Untrusted response member. @returns Whether it is a source object. */
        (source: unknown): source is Record<string, unknown> => typeof source === "object" && source !== null,
      );
    },
  );
  return <section className="space-y-5 rounded-xl border border-slate-200 bg-white p-6">
    <h3 className="font-semibold">RAG Evidence &amp; Evaluation Details</h3>
    <p className="text-sm text-slate-500">执行成功表示程序完成；质量是否达标需要查看检索、引用及答案判定。以下内容来自本次持久化 Trace 和 Metric。</p>
    {sources.length > 0 ? <div className="space-y-3">{sources.map(
      /** @param source Actual retrieved source. @param index Rank in the persisted result. @returns Versioned readable source card. */
      (source, index) => <details key={String(source.chunk_id) + index} className="rounded-lg border border-slate-200 p-4">
        <summary className="cursor-pointer break-words text-sm font-medium">#{index + 1} · {String(source.document)} · score {Number(source.score).toFixed(4)}</summary>
        <p className="mt-2 break-all text-xs text-slate-500">Chunk: {String(source.chunk_id)} · Version: {String(source.version)}</p>
        <pre className="mt-3 whitespace-pre-wrap break-words text-sm">{String(source.text)}</pre>
      </details>,
    )}</div> : <p className="text-sm text-slate-500">No accepted retrieval evidence in this run. Check the trace for gate rejection or dependency failure.</p>}
    <div className="space-y-3">{run.result.metrics.map(
      /** @param metric Actual metric calculation. @returns Applicable/N/A score with full label and matching evidence. */
      (metric) => <details key={metric.name} className="rounded-lg border border-slate-200 p-4">
        <summary className="cursor-pointer text-sm">{metric.name} · {metric.score === null ? "N/A" : metric.score.toFixed(3)}</summary>
        <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 text-xs">{JSON.stringify(metric.details, null, 2)}</pre>
      </details>,
    )}</div>
  </section>;
}
