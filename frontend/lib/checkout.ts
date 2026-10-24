export type CheckoutAttempt = { key: string; version: number; orderId?: string };

export function checkoutSlot(sessionKey: string): string {
  return `checkout:pending:${sessionKey}`;
}

export function readCheckout(sessionKey: string): CheckoutAttempt | null {
  const raw = sessionStorage.getItem(checkoutSlot(sessionKey));
  if (!raw) return null;
  try {
    const value = JSON.parse(raw);
    if (typeof value?.key === "string" && /^[0-9a-f-]{36}$/i.test(value.key)
      && Number.isSafeInteger(value.version) && value.version >= 0
      && (value.orderId === undefined || typeof value.orderId === "string")) return value;
  } catch { /* An incomplete local record cannot identify a checkout attempt. */ }
  sessionStorage.removeItem(checkoutSlot(sessionKey));
  return null;
}
