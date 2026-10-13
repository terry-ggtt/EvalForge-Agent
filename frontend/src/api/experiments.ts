import {
  apiRequest,
} from "./client";

import type {
  Experiment,
  ExperimentListResponse,
  RunExperimentRequest,
} from "../types/api";


export function getExperiments(
  limit = 100,
) {

  return apiRequest<
    ExperimentListResponse
  >(
    `/experiments?limit=${limit}`,
  );
}


export function runExperiment(
  request:
    RunExperimentRequest,
) {

  return apiRequest<
    Experiment
  >(
    "/experiments/run",
    {
      method:
        "POST",

      body:
        JSON.stringify(
          request
        ),
    },
  );
}

/** @param experimentId Opaque ID. @param signal Query cancellation. @returns Persisted experiment and its run membership. */
export function getExperiment(experimentId: string, signal?: AbortSignal) {
  return apiRequest<Experiment>(`/experiments/${encodeURIComponent(experimentId)}`, { signal });
}
