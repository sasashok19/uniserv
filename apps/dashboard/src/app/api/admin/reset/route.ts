import { NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/**
 * Admin DB reset (UI_REVAMP_v2 Feature D) — proxies `{password, confirmation}`
 * to the gateway, which verifies role + password + the literal "RESET" before
 * asking db-writer to wipe the tenant (rate-limited there).
 */
export async function POST(request: Request) {
  const body = await request.text();
  const resp = await gatewayFetch("/api/v1/admin/reset", { method: "POST", body });
  const data = await resp.json().catch(() => ({}));
  return NextResponse.json(data, { status: resp.status });
}
