/**
 * Landing page content (Feature 25) — the tenant-configurable copy, logo and
 * palette behind the public `/` page. The gateway owns the real defaults
 * (`LandingPageContent.java`); the copy below is a client-side mirror used only
 * when the gateway cannot be reached at all, so the front door still renders a
 * complete page when db-writer is cold or the gateway is redeploying.
 *
 * Keep the two in sync — a drift shows up as the page changing wording the
 * moment the backend comes back, which reads as a bug to a citizen.
 *
 * This module must stay free of server-only imports: `LandingPagePanel` is a
 * client component and imports the defaults and {@link coerceLandingPage} from
 * here. The server-side read lives in `landingPage.server.ts` because
 * `lib/gateway` pulls in `next/headers`, which cannot be bundled for the
 * browser.
 */

export type LandingSection = { heading: string; body: string };
export type LandingContactSection = LandingSection & {
  email: string;
  phone: string;
  whatsapp: string;
  address: string;
  hours: string;
};
export type LandingFooterLink = { label: string; url: string };
export type LandingColors = {
  from: string;
  via: string;
  to: string;
  accent: string;
  accentTo: string;
};

export type LandingPageContent = {
  brandName: string;
  logoUrl: string;
  tagline: string;
  subTagline: string;
  trackHeading: string;
  trackHelp: string;
  trackPlaceholder: string;
  trackButtonLabel: string;
  notFiledText: string;
  agentSignInLabel: string;
  agentSignInCaption: string;
  footerNote: string;
  colors: LandingColors;
  about: LandingSection;
  howItWorks: LandingSection;
  contact: LandingContactSection;
  sections: LandingSection[];
  footerLinks: LandingFooterLink[];
};

export const DEFAULT_LANDING_PAGE: LandingPageContent = {
  brandName: "UniServe",
  logoUrl: "",
  tagline: "The complaint that gets heard.",
  subTagline: "Multi-tenant AI-powered complaint & feedback portal",
  trackHeading: "Track your complaint",
  trackHelp:
    "Enter your ticket number (e.g. TKT-00042), your ANON-XXXX reference, or the email address you wrote in from.",
  trackPlaceholder: "TKT-00042, ANON-1234, or you@example.com",
  trackButtonLabel: "Track complaint",
  notFiledText:
    "Haven't filed a complaint yet? Reach us by Email or WhatsApp and we'll take it from there.",
  agentSignInLabel: "Agent sign in",
  agentSignInCaption: "For UniServe staff and support agents",
  footerNote: "UniServe — multi-tenant complaint & feedback portal",
  colors: {
    from: "#0D1B2A",
    via: "#1B3A52",
    to: "#028090",
    accent: "#F4A261",
    accentTo: "#E07B54",
  },
  about: {
    heading: "About us",
    body:
      "We are here to make sure every complaint reaches a person who can act on it, and that you can see what happened to it.",
  },
  howItWorks: {
    heading: "How it works",
    body:
      "Write to us by email or WhatsApp in your own words. We read it, route it to the right team, and give you a reference number you can track on this page.",
  },
  contact: {
    heading: "Contact us",
    body: "Reach us any way that suits you — we will reply on the same channel.",
    email: "",
    phone: "",
    whatsapp: "",
    address: "",
    hours: "",
  },
  sections: [],
  footerLinks: [],
};

/** Only these two shapes may reach an `<img src>` / `<a href>` — see the same
 *  rule in `LandingPageContent.java`. Re-checked client-side because this file
 *  also renders the admin panel's live preview, which never round-trips the
 *  gateway's validator. */
function isSafeUrl(url: string, allowMailtoTel = false): boolean {
  if (url.startsWith("//")) return false;
  if (url.startsWith("/") || url.startsWith("http://") || url.startsWith("https://")) return true;
  return allowMailtoTel && (url.startsWith("mailto:") || url.startsWith("tel:"));
}

/** Merge an untrusted/partial payload over the defaults. Never throws. */
export function coerceLandingPage(raw: unknown): LandingPageContent {
  const src = (raw ?? {}) as Record<string, unknown>;
  const str = (v: unknown, fallback: string) => {
    const s = typeof v === "string" ? v.trim() : "";
    return s === "" ? fallback : s;
  };
  const d = DEFAULT_LANDING_PAGE;
  const rawColors = (src.colors ?? {}) as Record<string, unknown>;
  const hex = (v: unknown, fallback: string) =>
    typeof v === "string" && /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(v.trim())
      ? v.trim()
      : fallback;

  const section = (key: "about" | "howItWorks", fallback: typeof d.about) => {
    const s = (src[key] ?? {}) as Record<string, unknown>;
    return { heading: str(s.heading, fallback.heading), body: str(s.body, fallback.body) };
  };

  const rawContact = (src.contact ?? {}) as Record<string, unknown>;
  const contactField = (v: unknown) => (typeof v === "string" ? v.trim() : "");

  const logoUrl = typeof src.logoUrl === "string" ? src.logoUrl.trim() : "";

  return {
    brandName: str(src.brandName, d.brandName),
    logoUrl: isSafeUrl(logoUrl) ? logoUrl : "",
    tagline: str(src.tagline, d.tagline),
    subTagline: str(src.subTagline, d.subTagline),
    trackHeading: str(src.trackHeading, d.trackHeading),
    trackHelp: str(src.trackHelp, d.trackHelp),
    trackPlaceholder: str(src.trackPlaceholder, d.trackPlaceholder),
    trackButtonLabel: str(src.trackButtonLabel, d.trackButtonLabel),
    notFiledText: str(src.notFiledText, d.notFiledText),
    agentSignInLabel: str(src.agentSignInLabel, d.agentSignInLabel),
    agentSignInCaption: str(src.agentSignInCaption, d.agentSignInCaption),
    footerNote: str(src.footerNote, d.footerNote),
    colors: {
      from: hex(rawColors.from, d.colors.from),
      via: hex(rawColors.via, d.colors.via),
      to: hex(rawColors.to, d.colors.to),
      accent: hex(rawColors.accent, d.colors.accent),
      accentTo: hex(rawColors.accentTo, d.colors.accentTo),
    },
    about: section("about", d.about),
    howItWorks: section("howItWorks", d.howItWorks),
    contact: {
      heading: str(rawContact.heading, d.contact.heading),
      body: str(rawContact.body, d.contact.body),
      email: contactField(rawContact.email),
      phone: contactField(rawContact.phone),
      whatsapp: contactField(rawContact.whatsapp),
      address: contactField(rawContact.address),
      hours: contactField(rawContact.hours),
    },
    sections: Array.isArray(src.sections)
      ? src.sections
          .map((s) => {
            const row = (s ?? {}) as Record<string, unknown>;
            return {
              heading: typeof row.heading === "string" ? row.heading.trim() : "",
              body: typeof row.body === "string" ? row.body.trim() : "",
            };
          })
          .filter((s) => s.heading !== "")
      : [],
    footerLinks: Array.isArray(src.footerLinks)
      ? src.footerLinks
          .map((l) => {
            const row = (l ?? {}) as Record<string, unknown>;
            return {
              label: typeof row.label === "string" ? row.label.trim() : "",
              url: typeof row.url === "string" ? row.url.trim() : "",
            };
          })
          .filter((l) => l.label !== "" && isSafeUrl(l.url, true))
      : [],
  };
}
