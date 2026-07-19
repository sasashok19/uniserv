import { NextRequest, NextResponse } from "next/server";

import { gatewayBase } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/** Logout: revoke the refresh token at the gateway, then clear both cookies. */
export async function POST(request: NextRequest) {
  const refresh = request.cookies.get("refresh_token")?.value;
  try {
    await fetch(`${gatewayBase()}/api/v1/auth/logout`, {
      method: "POST",
      headers: refresh ? { cookie: `refresh_token=${refresh}` } : undefined,
      cache: "no-store",
    });
  } catch {
    // Best-effort revoke — clearing the cookies below logs the browser out regardless.
  }
  const res = NextResponse.json({ ok: true });
  for (const name of ["access_token", "role", "refresh_token"]) {
    res.cookies.set(name, "", { path: "/", maxAge: 0 });
  }
  return res;
}
