import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Judge an unrouted message noise (Feature 24). Kept as a row, never deleted. */
export async function POST(
  _request: Request,
  { params }: { params: { id: string } },
) {
  const resp = await gatewayFetch(`/api/v1/unrouted-messages/${params.id}/discard`, {
    method: "POST",
    body: "{}",
  });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
