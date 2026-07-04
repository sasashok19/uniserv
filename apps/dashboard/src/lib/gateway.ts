import { cookies } from "next/headers";

/**
 * Server-side base URL for the api-gateway. Inside the container we reach the
 * gateway by its service name; NEXT_PUBLIC_* is the browser-facing URL.
 */
export function gatewayBase(): string {
  return (
    process.env.API_GATEWAY_INTERNAL_URL ||
    process.env.NEXT_PUBLIC_API_GATEWAY_URL ||
    "http://localhost:8080"
  );
}

/** Fetch the gateway, forwarding the access_token cookie as a Bearer token. */
export async function gatewayFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const token = cookies().get("access_token")?.value;
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${gatewayBase()}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}
