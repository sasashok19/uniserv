import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Admin: read per-channel configurable intake fields (Feature 16) — RBAC enforced by the gateway. */
export async function GET() {
  const resp = await gatewayFetch("/api/v1/tenant/intake-fields");
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}

/** Admin: update per-channel configurable intake fields (Feature 16) — RBAC enforced by the gateway. */
export async function PUT(request: Request) {
  const body = await request.text();
  const resp = await gatewayFetch("/api/v1/tenant/intake-fields", { method: "PUT", body });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
