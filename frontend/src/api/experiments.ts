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