import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Ticket audit trail (created / assigned / status transitions) for the detail page. */
export async function GET(_request: Request, { params }: { params: { id: string } }) {
  const resp = await gatewayFetch(`/api/v1/tickets/${params.id}/events`);
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
