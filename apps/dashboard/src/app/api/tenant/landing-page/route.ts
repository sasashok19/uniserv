import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Admin: read landing page content (Feature 25) — RBAC enforced by the gateway. */
export async function GET() {
  const resp = await gatewayFetch("/api/v1/tenant/landing-page");
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}

/** Admin: update landing page content (Feature 25) — RBAC enforced by the gateway. */
export async function PUT(request: Request) {
  const body = await request.text();
  const resp = await gatewayFetch("/api/v1/tenant/landing-page", { method: "PUT", body });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
