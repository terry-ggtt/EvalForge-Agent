import type { TimelineEvent } from "../types/api";

export type TraceFilter = "all" | "tools" | "models" | "errors" | "runtime";

/** @param events Persisted ordered events. @param filter Selected view. @returns Filtered events without reordering or modifying timestamps. */
export function filterTraceEvents(events: TimelineEvent[], filter: TraceFilter): TimelineEvent[] {
  return events.filter(
    /** @param event Actual event. @returns Whether its kind belongs to the requested view. */
    (event) => filter === "all"
      || (filter === "tools" && event.event_type.startsWith("tool_"))
      || (filter === "models" && event.event_type.startsWith("model_"))
      || (filter === "errors" && event.event_type === "error")
      || (filter === "runtime" && !["tool_call", "tool_result", "model_call", "model_result", "error"].includes(event.event_type)),
  );
}

/** @param event Actual observation. @returns Human-readable component identity without inferring hidden reasoning. */
export function traceLabel(event: TimelineEvent): string {
  const name = event.payload.tool_name ?? event.payload.purpose;
  return typeof name === "string" ? name : event.event_type;
}
