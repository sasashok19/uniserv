import { NextRequest, NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/**
 * Unrouted citizen messages (Feature 24) — messages routing could not attribute
 * to any ticket and deliberately did not invent one for. Lead/admin only; the
 * gateway enforces that, this is a pass-through so a 403 reaches the UI intact.
 */
export async function GET(request: NextRequest) {
  const qs = request.nextUrl.searchParams.toString();
  const resp = await gatewayFetch(`/api/v1/unrouted-messages${qs ? `?${qs}` : ""}`);
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
