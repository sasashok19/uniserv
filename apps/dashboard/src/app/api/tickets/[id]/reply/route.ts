import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Send an update to the citizen (Feature 12/14) — emails on email-origin tickets. */
export async function POST(
  request: Request,
  { params }: { params: { id: string } },
) {
  const body = await request.text();
  const resp = await gatewayFetch(`/api/v1/tickets/${params.id}/reply`, {
    method: "POST",
    body,
  });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
