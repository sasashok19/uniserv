import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Lead/Admin: assign or unassign a ticket (Feature 15) — RBAC enforced by the gateway. */
export async function PATCH(
  request: Request,
  { params }: { params: { id: string } },
) {
  const body = await request.text();
  const resp = await gatewayFetch(`/api/v1/tickets/${params.id}/assign`, { method: "PATCH", body });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
