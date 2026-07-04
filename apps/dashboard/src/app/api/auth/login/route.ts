import { NextRequest, NextResponse } from "next/server";

import { gatewayBase } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/**
 * Dashboard login (Feature 12): proxies to the gateway, then stores the access
 * token in an `access_token` cookie and the role in a readable `role` cookie for
 * client-side tab gating. The gateway's HttpOnly refresh cookie is forwarded too.
 */
export async function POST(request: NextRequest) {
  const body = await request.text();
  const resp = await fetch(`${gatewayBase()}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    cache: "no-store",
  });

  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    return NextResponse.json(data, { status: resp.status });
  }

  const res = NextResponse.json({ role: data.role, expires_in: data.expires_in });
  const maxAge = data.expires_in ?? 900;
  res.cookies.set("access_token", data.access_token, {
    httpOnly: true,
    path: "/",
    maxAge,
    sameSite: "lax",
  });
  res.cookies.set("role", data.role ?? "", {
    httpOnly: false,
    path: "/",
    maxAge,
    sameSite: "lax",
  });

  // Forward the gateway's refresh_token cookie to the browser.
  const setCookie = resp.headers.get("set-cookie");
  if (setCookie) res.headers.append("set-cookie", setCookie);
  return res;
}
