import { notFound } from "next/navigation";
import { backend } from "@/lib/server";
import type { Product } from "@/lib/types";
import { AddToCart } from "@/components/add-to-cart";
export const dynamic = "force-dynamic";

export default async function ProductPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[1-9]\d{0,17}$/.test(id) || BigInt(id) > BigInt(Number.MAX_SAFE_INTEGER)) notFound();
  const response = await backend(`/api/products/${id}`);
  if (response.status === 404) notFound();
  if (!response.ok) throw new Error("Не удалось загрузить товар");
  const product: Product = await response.json();
  return <><h1>{product.name}</h1><img src={product.image_url} alt={product.name} width="480" height="360" />
    <AddToCart productId={product.id} /></>;
}
