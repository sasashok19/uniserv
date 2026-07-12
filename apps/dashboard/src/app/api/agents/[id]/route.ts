import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Admin: edit agent details (name/role/active) — email is immutable, gateway-enforced. */
export async function PATCH(
  request: Request,
  { params }: { params: { id: string } },
) {
  const body = await request.text();
  const resp = await gatewayFetch(`/api/v1/agents/${params.id}`, { method: "PATCH", body });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}

/** Admin: deactivate an agent (soft delete). */
export async function DELETE(
  _request: Request,
  { params }: { params: { id: string } },
) {
  const resp = await gatewayFetch(`/api/v1/agents/${params.id}`, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
