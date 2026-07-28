import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Service health for the Administration → System panel. Server-side so the
 * browser doesn't need cross-origin access to each service; short timeout per
 * probe and never throws.
 *
 * Base URLs are configurable (API_GATEWAY_INTERNAL_URL/NEXT_PUBLIC_API_GATEWAY_URL,
 * DB_WRITER_URL, AI_CORE_URL) rather than hardcoded to localhost — on a
 * single-host Docker/local-dev setup those default ports are correct, but on
 * Vercel there's no localhost to reach, so every service showed "Unreachable"
 * until pointed at each service's real deployed URL (Render/Railway).
 */
function baseUrl(envVar: string | undefined, fallback: string): string {
  return (envVar || fallback).replace(/\/+$/, "");
}

const SERVICES = [
  {
    name: "api-gateway",
    base: baseUrl(process.env.API_GATEWAY_INTERNAL_URL || process.env.NEXT_PUBLIC_API_GATEWAY_URL, "http://localhost:8080"),
    path: "/q/health/ready",
  },
  {
    name: "db-writer",
    base: baseUrl(process.env.DB_WRITER_URL, "http://localhost:8090"),
    path: "/q/health/ready",
  },
  {
    name: "ai-core",
    base: baseUrl(process.env.AI_CORE_URL, "http://localhost:8001"),
    path: "/api/v1/health",
  },
];

/** Port for display: the URL's own port, else the scheme default (443/80). */
function displayPort(base: string): number {
  const parsed = new URL(base);
  if (parsed.port) return Number(parsed.port);
  return parsed.protocol === "https:" ? 443 : 80;
}

export async function GET() {
  const services = await Promise.all(
    SERVICES.map(async ({ name, base, path }) => {
      const port = displayPort(base);
      try {
        const resp = await fetch(`${base}${path}`, { cache: "no-store", signal: AbortSignal.timeout(3000) });
        return { name, port, status: resp.ok ? "healthy" : "unhealthy" };
      } catch {
        return { name, port, status: "unhealthy" };
      }
    }),
  );
  return NextResponse.json({ services });
}
