import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Admin: read tenant general settings (Feature 4) — RBAC enforced by the gateway. */
export async function GET() {
  const resp = await gatewayFetch("/api/v1/tenant/general-settings");
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}

/** Admin: update tenant general settings (Feature 4) — RBAC enforced by the gateway. */
export async function PUT(request: Request) {
  const body = await request.text();
  const resp = await gatewayFetch("/api/v1/tenant/general-settings", { method: "PUT", body });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
