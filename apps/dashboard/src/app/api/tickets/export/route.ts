import { NextRequest, NextResponse } from "next/server";

import { gatewayFetch } from "@/lib/gateway";

export const dynamic = "force-dynamic";

/**
 * Ticket CSV export (Feature 21) — proxies to the gateway, which applies the
 * `ticket.export` permission and does the paging.
 *
 * Unlike the sibling queue route this must NOT parse the body as JSON: the
 * payload is CSV, and it is streamed straight through with its
 * Content-Disposition intact so the browser saves a file rather than
 * rendering it. An error from the gateway still arrives as JSON, so that case
 * is passed through as-is for the caller to surface.
 */
export async function GET(request: NextRequest) {
  const qs = request.nextUrl.searchParams.toString();
  const resp = await gatewayFetch(`/api/v1/tickets/export.csv${qs ? `?${qs}` : ""}`);

  if (!resp.ok) {
    const data = await resp.json().catch(() => ({ error: { message: "Export failed" } }));
    return NextResponse.json(data, { status: resp.status });
  }

  const body = await resp.text();
  const headers = new Headers({
    "Content-Type": "text/csv; charset=utf-8",
    "Content-Disposition":
      resp.headers.get("Content-Disposition") ?? 'attachment; filename="uniserve-tickets.csv"',
  });
  const truncated = resp.headers.get("X-Export-Truncated");
  const rowCount = resp.headers.get("X-Export-Row-Count");
  if (truncated) headers.set("X-Export-Truncated", truncated);
  if (rowCount) headers.set("X-Export-Row-Count", rowCount);
  return new NextResponse(body, { status: 200, headers });
}
