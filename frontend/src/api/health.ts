import {
  apiRequest,
} from "./client";

import type {
  HealthResponse,
} from "../types/api";


export function getHealth() {
  return apiRequest<HealthResponse>(
    "/health",
  );
}