import { gatewayBase } from "@/lib/gateway";
import {
  DEFAULT_LANDING_PAGE,
  coerceLandingPage,
  type LandingPageContent,
} from "@/lib/landingPage";

/**
 * Server-side read of the public landing page content (Feature 25). Split from
 * `landingPage.ts` because `lib/gateway` imports `next/headers`, which cannot
 * be bundled into the client — and `LandingPagePanel` (a client component)
 * needs the defaults and coercion from that module. The `.server` suffix is the
 * marker here rather than the `server-only` package, which this app does not
 * depend on — importing this file from a client component fails the build with
 * a `next/headers` error, which is the same guard by a noisier route.
 *
 * Never throws and never returns a partial object: any failure — gateway
 * redeploying, db-writer cold, malformed payload — degrades to
 * {@link DEFAULT_LANDING_PAGE} so the front door always renders complete copy.
 *
 * Cached for 60s (the page itself is ISR at the same interval), so an admin's
 * save shows up publicly within about a minute rather than costing a gateway
 * round-trip on every visit — which matters when the gateway is a free-tier
 * instance that may be cold.
 */
export async function fetchLandingPage(): Promise<LandingPageContent> {
  try {
    const resp = await fetch(`${gatewayBase()}/api/v1/public/landing-page`, {
      next: { revalidate: 60 },
      signal: AbortSignal.timeout(5000),
    });
    if (!resp.ok) return DEFAULT_LANDING_PAGE;
    const data = await resp.json();
    return coerceLandingPage(data?.content);
  } catch {
    return DEFAULT_LANDING_PAGE;
  }
}
