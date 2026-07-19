import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Service health for the Administration → System panel. Server-side so the
 * browser doesn't need cross-origin access to each service; short timeout per
 * probe and never throws.
 */
const SERVICES = [
  { name: "api-gateway", port: 8080, url: "http://localhost:8080/q/health/ready" },
  { name: "db-writer", port: 8090, url: "http://localhost:8090/q/health/ready" },
  { name: "ai-core", port: 8001, url: "http://localhost:8001/api/v1/health" },
];

export async function GET() {
  const services = await Promise.all(
    SERVICES.map(async ({ name, port, url }) => {
      try {
        const resp = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(3000) });
        return { name, port, status: resp.ok ? "healthy" : "unhealthy" };
      } catch {
        return { name, port, status: "unhealthy" };
      }
    }),
  );
  return NextResponse.json({ services });
}
