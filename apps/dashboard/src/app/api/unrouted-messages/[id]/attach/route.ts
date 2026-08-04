import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/**
 * File an unrouted message against the ticket it belonged to (Feature 24).
 * Accepts `{ticketNumber}` — what the agent is actually reading — and the
 * gateway resolves it to an id.
 */
export async function POST(
  request: Request,
  { params }: { params: { id: string } },
) {
  const body = await request.text();
  const resp = await gatewayFetch(`/api/v1/unrouted-messages/${params.id}/attach`, {
    method: "POST",
    body,
  });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
