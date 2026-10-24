export type Product = { id: number; name: string; image_url: string };
export type Cart = { version: number; items: { product_id: number; name: string; image_url: string; quantity: number }[] };
export type Order = { id: string; created_at: string; items: { product_id: number; name: string; quantity: number }[] };
