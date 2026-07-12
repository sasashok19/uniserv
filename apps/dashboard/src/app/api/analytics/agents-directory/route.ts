import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

export async function GET() {
  const resp = await gatewayFetch("/api/v1/analytics/agents-directory");
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
