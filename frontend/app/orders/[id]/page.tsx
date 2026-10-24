"use client";
import { use, useEffect, useState } from "react";
import { useSession } from "@/components/session";
import { checkoutSlot, readCheckout } from "@/lib/checkout";
import type { Order } from "@/lib/types";

export default function OrderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { ready, request, sessionKey } = useSession();
  const [order, setOrder] = useState<Order | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (ready) request<Order>(`/api/orders/${encodeURIComponent(id)}`).then(value => {
      setOrder(value);
      if (sessionKey && readCheckout(sessionKey)?.orderId === value.id) sessionStorage.removeItem(checkoutSlot(sessionKey));
    }).catch((e: Error) => setError(e.message));
  }, [id, ready, request, sessionKey]);
  return <><h1>Заказ</h1>{error ? <p role="alert">{error}</p> : !order ? <p role="status">Загрузка заказа…</p> : <>
    <p>Заказ оформлен.</p><p>Идентификатор: <strong>{order.id}</strong></p>
    <p>Дата: <time dateTime={order.created_at}>{new Date(order.created_at).toLocaleString("ru-RU")}</time></p>
    <ul>{order.items.map(item => <li key={item.product_id}>{item.name} — {item.quantity} шт.</li>)}</ul>
  </>}</>;
}
