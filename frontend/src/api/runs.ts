import {
  apiRequest,
} from "./client";

import type {
  RunDetail,
  RunListResponse,
  RunStatus,
  RunTimeline,
} from "../types/api";


export interface GetRunsParams {
  caseId?: string;

  status?: RunStatus | "";

  minScore?: number;

  maxScore?: number;

  limit?: number;

  offset?: number;

  order?:
    | "started_at_desc"
    | "started_at_asc";
}


export function getRuns(
  params: GetRunsParams = {},
) {

  const search =
    new URLSearchParams();


  if (
    params.caseId
  ) {
    search.set(
      "case_id",
      params.caseId,
    );
  }


  if (
    params.status
  ) {
    search.set(
      "status",
      params.status,
    );
  }


  if (
    params.minScore
    !== undefined
  ) {
    search.set(
      "min_score",
      String(
        params.minScore
      ),
    );
  }


  if (
    params.maxScore
    !== undefined
  ) {
    search.set(
      "max_score",
      String(
        params.maxScore
      ),
    );
  }


  search.set(
    "limit",
    String(
      params.limit
      ?? 20
    ),
  );


  search.set(
    "offset",
    String(
      params.offset
      ?? 0
    ),
  );


  search.set(
    "order",
    params.order
    ?? "started_at_desc",
  );


  return apiRequest<
    RunListResponse
  >(
    `/runs?${search.toString()}`,
  );
}


export function getRun(
  runId: string,
) {

  return apiRequest<
    RunDetail
  >(
    `/runs/${runId}`,
  );
}


export function getRunTimeline(
  runId: string,
) {

  return apiRequest<
    RunTimeline
  >(
    `/runs/${runId}/timeline`,
  );
}