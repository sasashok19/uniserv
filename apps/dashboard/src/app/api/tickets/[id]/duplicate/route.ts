import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/**
 * Feature 22: an agent's verdict on a suspected duplicate — confirm the merge
 * or dismiss the flag. RBAC and the merge itself are applied in the gateway;
 * this is a pass-through so 403/422 reach the UI intact.
 */
export async function POST(
  request: Request,
  { params }: { params: { id: string } },
) {
  const body = await request.text();
  const resp = await gatewayFetch(`/api/v1/tickets/${params.id}/duplicate`, {
    method: "POST",
    body,
  });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
