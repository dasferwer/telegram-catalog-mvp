"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { fetchJSON, RequestError } from "@/lib/http";
import { checkoutSlot, readCheckout } from "@/lib/checkout";
export { RequestError } from "@/lib/http";

declare global {
  interface Window { Telegram?: { WebApp?: { initData: string; ready(): void; expand(): void } } }
}

type Session = { csrf_token: string; kind: "guest" | "telegram"; checkout_scope: string; created?: boolean };
type Client = { ready: boolean; error: string; sessionKey: string | null; request<T>(path: string, init?: RequestInit): Promise<T> };
const Context = createContext<Client | null>(null);

function parseSession(value: unknown): Session {
  if (!value || typeof value !== "object" || !("csrf_token" in value) || !("kind" in value)
    || !("checkout_scope" in value) || typeof value.csrf_token !== "string" || !value.csrf_token
    || typeof value.checkout_scope !== "string" || !/^[0-9a-f-]{36}$/i.test(value.checkout_scope)
    || ("created" in value && typeof value.created !== "boolean")
    || (value.kind !== "guest" && value.kind !== "telegram")) throw new Error("Сервер вернул некорректную сессию.");
  return value as Session;
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState("");
  const started = useRef(false);
  const current = useRef<Session | null>(null);
  const reopen = useRef<(() => Promise<Session>) | null>(null);
  const refreshing = useRef<Promise<Session> | null>(null);
  const pristineGuest = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    (async () => {
      const params = new URLSearchParams(window.location.hash.slice(1));
      const launch = params.has("tgWebAppData") || params.has("tgWebAppVersion")
        || !!window.Telegram?.WebApp?.initData || sessionStorage.getItem("telegram-launch") === "1";
      if (launch) {
        sessionStorage.setItem("telegram-launch", "1");
        if (!window.Telegram?.WebApp) {
          await new Promise<void>((resolve, reject) => {
            const script = document.createElement("script");
            script.src = "https://telegram.org/js/telegram-web-app.js";
            script.async = true;
            const timer = window.setTimeout(() => reject(new Error("Не удалось загрузить Telegram SDK. Откройте каталог заново.")), 8000);
            script.onload = () => { clearTimeout(timer); resolve(); };
            script.onerror = () => { clearTimeout(timer); reject(new Error("Не удалось загрузить Telegram SDK.")); };
            document.head.appendChild(script);
          });
        }
      }
      const telegram = window.Telegram?.WebApp;
      const initData = telegram?.initData || sessionStorage.getItem("telegram-init-data") || "";
      if (launch && !initData) throw new Error("Telegram не передал данные авторизации. Откройте каталог через бота.");
      const openSession = async (): Promise<Session> => {
        for (let attempt = 0; attempt < 3; attempt++) {
          let value = parseSession(await fetchJSON("/api/session"));
          if (initData) {
            try {
              value = parseSession(await fetchJSON("/api/session/telegram", { method: "POST", headers: {
                "Content-Type": "application/json", "X-CSRF-Token": value.csrf_token,
              }, body: JSON.stringify({ init_data: initData }) }));
              if (value.kind !== "telegram") throw new Error("Авторизация Telegram отклонена. Откройте каталог заново через бота.");
            } catch (cause) {
              if (cause instanceof RequestError && [401, 403, 409].includes(cause.status)) {
                if (attempt < 2) { await new Promise(resolve => setTimeout(resolve, 50)); continue; }
                throw new Error("Авторизация Telegram отклонена. Откройте каталог заново через бота.");
              }
              throw cause;
            }
            telegram?.ready();
            telegram?.expand();
          }
          return value;
        }
        throw new Error("Не удалось согласовать сессию. Обновите страницу.");
      };
      const synchronizedSession = async () => navigator.locks
        ? await navigator.locks.request("catalog-session", { signal: AbortSignal.timeout(35000) }, openSession)
        : await openSession();
      const value = await synchronizedSession();
      const legacy = readCheckout(value.csrf_token);
      if (legacy && !readCheckout(value.checkout_scope)) {
        sessionStorage.setItem(checkoutSlot(value.checkout_scope), JSON.stringify(legacy));
        sessionStorage.removeItem(checkoutSlot(value.csrf_token));
      }
      reopen.current = synchronizedSession;
      pristineGuest.current = !initData && value.kind === "guest" && value.created === true;
      current.current = value;
      setSession(value);
    })().catch((e: Error) => setError(e.name === "TimeoutError" ? "Истекло время ожидания. Обновите страницу." : e.message));
  }, []);

  const request = useCallback(async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
    if (!current.current) throw new Error(error || "Сессия загружается");
    let active = current.current;
    const cartRead = (init.method || "GET").toUpperCase() === "GET" && path === "/api/cart";
    // Even a failed mutation can have committed; never rebind that tab to another guest.
    if (!cartRead) pristineGuest.current = false;
    for (let attempt = 0; attempt < 3; attempt++) {
      if (current.current?.checkout_scope !== active.checkout_scope) throw new Error("Владелец сессии изменился. Откройте каталог заново.");
      const headers = new Headers(init.headers);
      headers.set("Content-Type", "application/json");
      headers.set("X-CSRF-Token", active.csrf_token);
      headers.set("X-Checkout-Scope", active.checkout_scope);
      try {
        const result = await fetchJSON<T>(path, { ...init, headers });
        if (current.current?.checkout_scope !== active.checkout_scope) throw new Error("Владелец сессии изменился. Откройте каталог заново.");
        if (!cartRead || !result || typeof result !== "object" || !("version" in result) || result.version !== 0
          || !("items" in result) || !Array.isArray(result.items) || result.items.length !== 0) pristineGuest.current = false;
        return result;
      }
      catch (cause) {
        if (!(cause instanceof RequestError) || !cause.sessionConflict || !reopen.current || attempt === 2) throw cause;
        refreshing.current ??= reopen.current().finally(() => { refreshing.current = null; });
        try {
          const value = await refreshing.current;
          const adopted = current.current?.checkout_scope === value.checkout_scope;
          if (!current.current || (current.current.checkout_scope !== active.checkout_scope && !adopted)
            || (value.checkout_scope !== active.checkout_scope && (!cartRead || active.kind !== "guest"
              || value.kind !== "guest" || (!adopted && !pristineGuest.current) || readCheckout(active.checkout_scope)))) {
            throw new Error("Владелец сессии изменился. Откройте каталог заново.");
          }
          active = value;
          current.current = value;
          setSession(value);
        } catch (cause) {
          current.current = null;
          setSession(null);
          setError(cause instanceof Error ? cause.message : "Не удалось восстановить сессию.");
          throw cause;
        }
      }
    }
    throw new Error("Не удалось согласовать сессию. Обновите страницу.");
  }, [error]);
  return <Context.Provider value={{ ready: !!session, error, sessionKey: session?.checkout_scope ?? null, request }}>
    {error && <p role="alert">{error}</p>}{children}
  </Context.Provider>;
}

export function useSession(): Client {
  const context = useContext(Context);
  if (!context) throw new Error("SessionProvider is required");
  return context;
}
