import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** AI resolution summary (Feature 12) — passes through 200 or 503 AI_UNAVAILABLE. */
export async function POST(
  _request: Request,
  { params }: { params: { id: string } },
) {
  const resp = await gatewayFetch(
    `/api/v1/tickets/${params.id}/generate-resolution-summary`,
    { method: "POST" },
  );
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
