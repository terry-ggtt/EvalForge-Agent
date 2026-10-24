import { apiRequest } from "./client";

/** @param token Explicit in-memory Registry credential. @param path Relative Registry route.
 * @param body JSON command; undefined means GET. @param signal Cancellation.
 * @returns Server JSON; preserves existing ApiClientError including 401/403/409/503.
 * Credentials are sent only to the configured API's Registry prefix.
 */
export function registryRequest<T>(token: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return apiRequest<T>(`/adapter-registry${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: { Authorization: `Bearer ${token}` },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal,
  });
}

/** @param id Opaque server identifier. @returns Safe single route segment. */
export function registryId(id: string | number): string {
  return encodeURIComponent(String(id));
}
