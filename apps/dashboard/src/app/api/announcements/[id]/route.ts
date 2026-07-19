import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Admin: edit announcement (title/body/isActive/expiresAt). */
export async function PATCH(request: Request, { params }: { params: { id: string } }) {
  const body = await request.text();
  const resp = await gatewayFetch(`/api/v1/announcements/${params.id}`, { method: "PATCH", body });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}

/** Admin: delete announcement. */
export async function DELETE(_request: Request, { params }: { params: { id: string } }) {
  const resp = await gatewayFetch(`/api/v1/announcements/${params.id}`, { method: "DELETE" });
  if (resp.status === 204) return new NextResponse(null, { status: 204 });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
