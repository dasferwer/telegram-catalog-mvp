export async function backend(path: string): Promise<Response> {
  return fetch(`${process.env.API_INTERNAL_URL || "http://localhost:8000"}${path}`, {
    cache: "no-store", signal: AbortSignal.timeout(8000),
  });
}
