// Thin fetch wrapper -- four read-only screens don't need a data-fetching
// library. Every call is a plain GET against the Vite dev proxy (see
// vite.config.ts), which forwards /api/* to the FastAPI app on :8000.

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, body.detail ?? response.statusText)
  }
  return response.json() as Promise<T>
}
