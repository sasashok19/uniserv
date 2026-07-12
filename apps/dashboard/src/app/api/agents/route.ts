import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Admin: list agents/leads (Feature 12/15) — RBAC enforced by the gateway. */
export async function GET() {
  const resp = await gatewayFetch("/api/v1/agents");
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}

/** Admin: create agent (Feature 12) — RBAC enforced by the gateway. */
export async function POST(request: Request) {
  const body = await request.text();
  const resp = await gatewayFetch("/api/v1/agents", { method: "POST", body });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
