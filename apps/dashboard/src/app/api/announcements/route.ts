import { NextRequest, NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Announcements list (any role) — RBAC enforced by the gateway. */
export async function GET(request: NextRequest) {
  const qs = request.nextUrl.searchParams.toString();
  const resp = await gatewayFetch(`/api/v1/announcements${qs ? `?${qs}` : ""}`);
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}

/** Admin: create announcement. */
export async function POST(request: Request) {
  const body = await request.text();
  const resp = await gatewayFetch("/api/v1/announcements", { method: "POST", body });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
