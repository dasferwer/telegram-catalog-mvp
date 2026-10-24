export class RequestError extends Error {
  constructor(message: string, public readonly status: number, public readonly sessionConflict = false) { super(message); }
}

export async function fetchJSON<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, cache: "no-store", signal: AbortSignal.timeout(15000) });
  } catch (cause) {
    const timeout = cause instanceof Error && cause.name === "TimeoutError";
    const error = new Error(timeout ? "Истекло время ожидания ответа сервера. Повторите запрос."
      : "Не удалось связаться с сервером. Проверьте соединение и повторите запрос.");
    if (timeout) error.name = "TimeoutError";
    throw error;
  }
  let body: unknown;
  try { body = await response.json(); }
  catch {
    throw new RequestError(response.status >= 500 ? "Сервис временно недоступен. Повторите запрос позже."
      : "Сервер вернул некорректный ответ. Повторите запрос.", response.status);
  }
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : null;
    throw new RequestError(typeof detail === "string" ? detail : "Запрос отклонён", response.status,
      response.status === 403 && (response.headers.get("X-CSRF-Error") === "1"
        || response.headers.get("X-Session-Error") === "owner"));
  }
  return body as T;
}
