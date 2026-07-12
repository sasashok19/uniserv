import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Ticket notes (Feature 12) — internal, agent-facing annotations. */
export async function GET(
  _request: Request,
  { params }: { params: { id: string } },
) {
  const resp = await gatewayFetch(`/api/v1/tickets/${params.id}/notes`);
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}

export async function POST(
  request: Request,
  { params }: { params: { id: string } },
) {
  const body = await request.text();
  const resp = await gatewayFetch(`/api/v1/tickets/${params.id}/notes`, {
    method: "POST",
    body,
  });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
