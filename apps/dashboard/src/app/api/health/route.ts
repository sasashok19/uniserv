import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/** Health endpoint for the dashboard service. */
export async function GET() {
  return NextResponse.json({ service: "dashboard", status: "UP" });
}
