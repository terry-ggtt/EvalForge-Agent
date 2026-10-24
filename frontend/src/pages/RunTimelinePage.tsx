import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router";
import { getRunTimeline } from "../api/runs";
import { JobError } from "../components/jobs/JobComponents";
import { filterTraceEvents, traceLabel } from "../utils/tracePresentation";
import type { TraceFilter } from "../utils/tracePresentation";
import type { TimelineEvent } from "../types/api";

/** @param props Actual persisted event. @returns Readable event metadata with complete expandable payload. */
function EventCard({ event }: { event: TimelineEvent }) {
  const duration = event.payload.duration_ms
    ?? (event.payload.metadata && typeof event.payload.metadata === "object" && "duration_ms" in event.payload.metadata
      ? event.payload.metadata.duration_ms : null);
  const args = event.payload.arguments;
  const query = args && typeof args === "object" && "query" in args ? args.query : event.payload.input_text;
  const error = event.event_type === "error";
  return <div className="grid grid-cols-[74px_1fr] gap-3 sm:grid-cols-[100px_1fr] sm:gap-5">
    <div className="pt-4 text-right"><p className="text-sm font-medium">+{event.relative_ms.toFixed(3)} ms</p>
      <p className="mt-1 text-xs text-slate-400">Δ {event.delta_ms.toFixed(3)} ms</p></div>
    <div className={`min-w-0 rounded-xl border p-5 ${error ? "border-red-200 bg-red-50" : "border-slate-200 bg-white"}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><p className="break-all font-semibold">{traceLabel(event)}</p>
          <p className="mt-1 text-xs text-slate-500">{event.event_type}{typeof duration === "number" ? ` · ${duration.toFixed(2)} ms` : ""}</p></div>
        <span className="text-xs text-slate-400">#{event.sequence}</span>
      </div>
      {typeof query === "string" && <p className="mt-3 whitespace-pre-wrap break-words text-sm">{query}</p>}
      {error && <p className="mt-3 break-words text-sm text-red-700">{String(event.payload.message ?? event.payload.error_type ?? "")}</p>}
      {event.attempt_id && <p className="mt-2 break-all text-xs text-slate-400">Attempt: {event.attempt_id}</p>}
      <details className="mt-4"><summary className="cursor-pointer text-xs font-medium text-slate-600">完整输入 / 输出 JSON</summary>
        <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-4 text-xs">{JSON.stringify(event.payload, null, 2)}</pre>
      </details>
    </div>
  </div>;
}

/** @returns The existing persisted Timeline, with readable component labels and event filters. */
export function RunTimelinePage() {
  const { runId = "" } = useParams<{ runId: string }>();
  const [filter, setFilter] = useState<TraceFilter>("all");
  const query = useQuery({
    queryKey: ["run-timeline", runId],
    /** @returns Actual server timeline with canonical timestamps and event sequence. */
    queryFn: () => getRunTimeline(runId),
    enabled: Boolean(runId),
  });
  if (query.isPending) return <p role="status" className="text-sm text-slate-500">Loading timeline…</p>;
  if (query.isError || !query.data) return <JobError error={query.error} />;
  const timeline = query.data;
  const events = filterTraceEvents(timeline.events, filter);
  return <div className="space-y-6">
    <div><Link to={`/runs/${encodeURIComponent(runId)}`} className="text-sm text-slate-500 hover:underline">← Run Detail</Link>
      <h2 className="mt-2 text-2xl font-semibold">Run Timeline</h2>
      <p className="mt-2 text-sm text-slate-500">Duration: {timeline.duration_ms.toFixed(2)} ms · {timeline.events.length} events</p>
      <p className="mt-1 text-xs text-slate-500">展示实际执行步骤、工具参数、返回与安全模型用量；不展示模型隐藏推理。</p>
    </div>
    <label className="flex flex-wrap items-center gap-3 text-sm"><span>Event filter</span>
      <select aria-label="Event filter" value={filter} onChange={
        /** @param event Selected type. @returns Updates the view only; does not execute the Agent again. */
        (event) => setFilter(event.target.value as TraceFilter)
      } className="rounded-lg border border-slate-300 bg-white px-3 py-2">
        <option value="all">All events</option><option value="tools">Tools</option>
        <option value="models">Models</option><option value="errors">Errors</option><option value="runtime">Runtime / Retry</option>
      </select><span className="text-slate-500">{events.length} shown</span>
    </label>
    <div className="space-y-3">{events.map(
      /** @param event Filtered actual event. @returns Stable event card preserving original sequence numbers. */
      (event) => <EventCard key={event.sequence} event={event} />,
    )}</div>
    {events.length === 0 && <p className="text-sm text-slate-500">No events match this filter.</p>}
  </div>;
}
