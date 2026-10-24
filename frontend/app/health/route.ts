import { hostname } from "node:os";
export const dynamic = "force-dynamic";
export function GET() { return Response.json({ status: "ok", instance: hostname() }, { headers: { "Cache-Control": "no-store" } }); }
