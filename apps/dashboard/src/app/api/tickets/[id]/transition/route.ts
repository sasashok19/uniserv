import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Status transition (Feature 12) — passes through 200/422/403 from the gateway. */
export async function POST(
  request: Request,
  { params }: { params: { id: string } },
) {
  const body = await request.text();
  const resp = await gatewayFetch(`/api/v1/tickets/${params.id}/transition`, {
    method: "POST",
    body,
  });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
