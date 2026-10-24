import assert from "node:assert/strict";
import { test } from "node:test";
import { filterTraceEvents, traceLabel } from "../src/utils/tracePresentation.ts";

test("trace filters retain actual ordering and source labels",
  /** @returns Checks that filtering never fabricates, duplicates or sorts observations. */
  () => {
    const events = [
      { sequence: 1, event_type: "agent_start", payload: {} },
      { sequence: 2, event_type: "tool_call", payload: { tool_name: "rag.dense" } },
      { sequence: 3, event_type: "tool_result", payload: { tool_name: "rag.dense" } },
      { sequence: 4, event_type: "model_call", payload: { purpose: "answer" } },
      { sequence: 5, event_type: "error", payload: { message: "explicit outage" } },
    ];
    assert.deepEqual(filterTraceEvents(events, "tools"), [events[1], events[2]]);
    assert.deepEqual(filterTraceEvents(events, "models"), [events[3]]);
    assert.deepEqual(filterTraceEvents(events, "errors"), [events[4]]);
    assert.deepEqual(filterTraceEvents(events, "runtime"), [events[0]]);
    assert.deepEqual(filterTraceEvents(events, "all"), events);
    assert.equal(traceLabel(events[1]), "rag.dense");
    assert.equal(traceLabel(events[3]), "answer");
    assert.equal(traceLabel(events[0]), "agent_start");
  });
