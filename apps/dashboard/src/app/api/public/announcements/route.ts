import { NextResponse } from "next/server";

import { gatewayBase } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Public login-page ticker: active announcement titles only — no auth. */
export async function GET() {
  try {
    const resp = await fetch(`${gatewayBase()}/api/v1/public/announcements`, { cache: "no-store" });
    const data = await resp.json().catch(() => ({}));
    return NextResponse.json(data, { status: resp.status });
  } catch {
    return NextResponse.json({ announcements: [] });
  }
}
