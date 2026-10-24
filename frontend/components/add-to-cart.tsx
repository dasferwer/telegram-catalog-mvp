"use client";
import { useState } from "react";
import Link from "next/link";
import type { Cart } from "@/lib/types";
import { useSession } from "./session";

export function AddToCart({ productId }: { productId: number }) {
  const { ready, request } = useSession();
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  async function add() {
    setBusy(true); setStatus("");
    try {
      const cart = await request<Cart>("/api/cart");
      const quantity = (cart.items.find(i => i.product_id === productId)?.quantity || 0) + 1;
      await request("/api/cart/items/" + productId, { method: "PUT", body: JSON.stringify({ quantity, version: cart.version }) });
      setStatus("Товар добавлен в корзину");
    } catch (e) { setStatus(e instanceof Error ? e.message : "Не удалось добавить товар"); }
    finally { setBusy(false); }
  }
  return <div><button disabled={!ready || busy} onClick={add}>{busy ? "Добавление…" : "Добавить в корзину"}</button>
    <p role="status">{status}</p><Link href="/cart">Перейти в корзину</Link></div>;
}
