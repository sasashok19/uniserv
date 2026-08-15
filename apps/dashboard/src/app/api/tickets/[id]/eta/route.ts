import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/**
 * Revise a ticket's ETA (Feature 26) — passes through 200/403/422 from the
 * gateway. The ETA is first captured as part of the first transition, where it
 * is mandatory; this covers the revisions that follow.
 */
export async function PATCH(
  request: Request,
  { params }: { params: { id: string } },
) {
  const body = await request.text();
  const resp = await gatewayFetch(`/api/v1/tickets/${params.id}/eta`, {
    method: "PATCH",
    body,
  });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
