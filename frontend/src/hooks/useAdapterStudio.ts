import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { registryRequest } from "../api/adapterStudio";
import { generationIsActive } from "../utils/adapterStudio";

/** @param token Session-only credential. @param path Fixed relative route, empty disables read.
 * @param polling True only for generation detail. @returns Cancellable query; terminal/error stops polling.
 */
export function useRegistryQuery<T>(token: string, path: string, polling = false) {
  return useQuery({
    queryKey: [path], enabled: Boolean(path), retry: false,
    /** @param context Query lifecycle cancellation. @returns Authorized server snapshot. */
    queryFn: ({ signal }) => registryRequest<T>(token, path, undefined, signal),
    /** @param query Current snapshot. @returns Two seconds while active, otherwise no polling. */
    refetchInterval: query => polling && !query.state.error && query.state.data
      && typeof query.state.data === "object" && "status" in query.state.data
      && typeof query.state.data.status === "string" && generationIsActive(query.state.data.status) ? 2000 : false,
  });
}

/** @param token Session credential. @param path Command route. @param done Success-only state transition.
 * @returns Single pending mutation; commands never auto-retry or auto-publish.
 */
export function useRegistryCommand<T>(token: string, path: string, done?: (row: T) => void) {
  const client = useQueryClient();
  return useMutation({
    /** @param body Explicit user command. @returns Server mutation response or existing client error. */
    mutationFn: (body: unknown) => registryRequest<T>(token, path, body),
    /** @param row Persisted response. @returns Invalidates this session's reads before updating selection. */
    onSuccess: async row => {
      await client.invalidateQueries();
      done?.(row);
    },
  });
}
