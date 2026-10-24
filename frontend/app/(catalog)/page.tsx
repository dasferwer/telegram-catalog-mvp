import Link from "next/link";
import { backend } from "@/lib/server";
import type { Product } from "@/lib/types";
export const dynamic = "force-dynamic";

export default async function Catalog({ searchParams }: { searchParams: Promise<{ before?: string }> }) {
  const { before } = await searchParams;
  const query = before && /^[1-9]\d*$/.test(before) ? "?before=" + before : "";
  let data: { items: Product[]; next_cursor: number | null };
  try {
    const response = await backend("/api/products" + query);
    if (!response.ok) throw new Error("unavailable");
    data = await response.json();
  } catch {
    return <><h1>Каталог</h1><p role="alert">Не удалось загрузить каталог.</p><a href="/">Повторить</a></>;
  }
  return <><h1>Каталог</h1>
    {data.items.length === 0 ? <p>В каталоге пока нет товаров.</p> : <ul className="products">{data.items.map(p => <li key={p.id}>
      <Link href={`/products/${p.id}`}><img src={p.image_url} alt={p.name} width="240" height="180" /><h2>{p.name}</h2></Link>
    </li>)}</ul>}
    {data.next_cursor && <Link href={`/?before=${data.next_cursor}`}>Следующие товары</Link>}
    {before && <p><Link href="/">Начало каталога</Link></p>}
  </>;
}
