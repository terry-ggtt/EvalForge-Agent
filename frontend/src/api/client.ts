import type {
  ApiErrorResponse,
} from "../types/api";


const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL
  ?? "http://127.0.0.1:8000";


export class ApiClientError extends Error {
  status: number;

  code: string;

  details: unknown;


  constructor(
    status: number,
    code: string,
    message: string,
    details: unknown = null,
  ) {
    super(message);

    this.name =
      "ApiClientError";

    this.status =
      status;

    this.code =
      code;

    this.details =
      details;
  }
}


export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {

  const response = await fetch(
    `${API_BASE_URL}${path}`,
    {
      ...init,

      headers: {
        "Content-Type":
          "application/json",

        ...init?.headers,
      },
    },
  );


  if (!response.ok) {

    let errorBody:
      ApiErrorResponse | null
      = null;

    try {

      errorBody =
        await response.json();

    } catch {

      // Response may not be JSON.
    }


    throw new ApiClientError(
      response.status,

      errorBody
        ?.error
        ?.code
        ?? "http_error",

      errorBody
        ?.error
        ?.message
        ?? `Request failed: ${response.status}`,

      errorBody
        ?.error
        ?.details
        ?? null,
    );
  }


  return (
    await response.json()
  ) as T;
}