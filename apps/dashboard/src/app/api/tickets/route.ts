import { NextRequest, NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Ticket queue (Feature 12) — proxies to the gateway with RBAC applied there. */
export async function GET(request: NextRequest) {
  const qs = request.nextUrl.searchParams.toString();
  const resp = await gatewayFetch(`/api/v1/tickets${qs ? `?${qs}` : ""}`);
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
