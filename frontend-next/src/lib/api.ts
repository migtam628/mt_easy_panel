/** The only network boundary. No bearer tokens or client-side credentials. */
export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  // Never allow user input to form an arbitrary external URL.
  if (!path.startsWith("/api/") || path.startsWith("//")) {
    throw new ApiError("Only same-origin /api requests are supported", 400);
  }
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  let data: unknown;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data &&
      typeof data.detail === "string" ? data.detail : "Request failed (" + response.status + ")";
    throw new ApiError(detail, response.status);
  }
  return data as T;
}

export type Envelope<T> = { data: T };
export type ApiRow = Record<string, unknown>;
export function asRows(value: unknown): ApiRow[] {
  return Array.isArray(value) ? value.filter(
    (item): item is ApiRow => item !== null && typeof item === "object" && !Array.isArray(item)
  ) : [];
}
export function asObject(value: unknown): ApiRow {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as ApiRow : {};
}
export function show(value: unknown): string {
  if (value === undefined || value === null || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return "—";
}
export function formatBytes(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? (value / 1024 ** 3).toFixed(1) + " GB" : "—";
}
export function formatTime(value: unknown): string {
  return typeof value === "number" && value > 0
    ? new Date(value * 1000).toLocaleString() : "—";
}
