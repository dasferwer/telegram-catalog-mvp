"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { RequestError, useSession } from "@/components/session";
import { checkoutSlot, readCheckout, type CheckoutAttempt } from "@/lib/checkout";
import type { Cart, Order } from "@/lib/types";

export default function CartPage() {
  const { ready, request, sessionKey } = useSession();
  const [cart, setCart] = useState<Cart | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<CheckoutAttempt | null>(null);
  const router = useRouter();
  const load = useCallback(async () => { setCart(await request<Cart>("/api/cart")); }, [request]);
  const submitCheckout = useCallback(async (attempt: CheckoutAttempt) => {
    if (!sessionKey) return;
    setBusy(true); setError("");
    try {
      if (attempt.orderId) {
        router.replace(`/orders/${attempt.orderId}`);
        return;
      }
      const order = await request<Order>("/api/orders", {
        method: "POST", headers: { "Idempotency-Key": attempt.key }, body: JSON.stringify({ version: attempt.version }),
      });
      sessionStorage.setItem(checkoutSlot(sessionKey), JSON.stringify({ ...attempt, orderId: order.id }));
      router.replace(`/orders/${order.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось оформить заказ. Повторите попытку.");
      if (e instanceof RequestError && (e.status === 409 || e.status === 422)) {
        sessionStorage.removeItem(checkoutSlot(sessionKey));
        setPending(null);
        await load().catch(() => {});
      }
    } finally { setBusy(false); }
  }, [sessionKey, request, router, load]);
  useEffect(() => {
    if (!ready || !sessionKey) return;
    (async () => {
      const attempt = readCheckout(sessionKey);
      setPending(attempt);
      await load().catch((e: Error) => setError(e.message));
      if (attempt) await submitCheckout(attempt);
    })().catch((e: Error) => setError(e.message));
  }, [ready, sessionKey, load, submitCheckout]);
  async function change(productId: number, quantity: number | null) {
    if (!cart || busy || pending) return;
    setBusy(true); setError("");
    try {
      setCart(await request<Cart>(`/api/cart/items/${productId}`, {
        method: quantity === null ? "DELETE" : "PUT",
        body: JSON.stringify({ version: cart.version, ...(quantity === null ? {} : { quantity }) }),
      }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка изменения корзины");
      await load().catch(() => {});
    } finally { setBusy(false); }
  }
  async function checkout() {
    if (!cart || busy || !sessionKey) return;
    try {
      const attempt = pending || readCheckout(sessionKey) || { key: crypto.randomUUID(), version: cart.version };
      sessionStorage.setItem(checkoutSlot(sessionKey), JSON.stringify(attempt));
      setPending(attempt);
      await submitCheckout(attempt);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось оформить заказ. Повторите попытку.");
    }
  }
  return <><h1>Корзина</h1>{error && <p role="alert">{error}</p>}
    {pending && <button disabled={busy} onClick={() => submitCheckout(pending)}>{busy ? "Обработка…" : "Повторить оформление"}</button>}
    {!cart ? <><p role="status">Загрузка корзины…</p>{ready && <button onClick={() => load().catch((e: Error) => setError(e.message))}>Обновить корзину</button>}</> : <>
      {!cart.items.length ? <p>Корзина пуста.</p> : <ul>{cart.items.map(item => <li className="cart-item" key={item.product_id}>
        <Link href={`/products/${item.product_id}`}>{item.name}</Link>
        <form onSubmit={event => { event.preventDefault(); const input = new FormData(event.currentTarget).get("quantity"); change(item.product_id, Number(input)); }}>
          <label>Количество «{item.name}» <input key={`${item.product_id}:${item.quantity}`} name="quantity" type="number" min="1" max="99" step="1" required defaultValue={item.quantity} disabled={busy || !!pending} /></label>
          <button disabled={busy || !!pending}>Сохранить количество</button>
          <button type="button" disabled={busy || !!pending} onClick={() => change(item.product_id, null)}>Удалить</button>
        </form>
      </li>)}</ul>}
      {!pending && <button disabled={busy || !cart.items.length} onClick={checkout}>{busy ? "Обработка…" : "Оформить заказ"}</button>}{" "}
      <button disabled={busy} onClick={() => { setError(""); load().catch((e: Error) => setError(e.message)); }}>Обновить корзину</button>
    </>}</>;
}
