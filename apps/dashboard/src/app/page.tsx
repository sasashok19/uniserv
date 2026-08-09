import Link from "next/link";

import TrackComplaintForm from "@/components/landing/TrackComplaintForm";
import { fetchLandingPage } from "@/lib/landingPage.server";
import type { LandingContactSection, LandingSection } from "@/lib/landingPage";

/**
 * Public landing page (Feature 12, made tenant-configurable in Feature 25).
 *
 * Every string, the logo and the palette come from the tenant's
 * `config_json.landingPage` via the unauthenticated
 * `/api/v1/public/landing-page` endpoint, so deploying for a different tenant
 * is an Administration → Landing Page edit rather than a code change. Unset
 * fields fall back to the copy this page shipped with, and an unreachable
 * gateway falls back to the same — the front door always renders.
 *
 * This is a SERVER component so the copy is in the initial HTML (no flash of
 * default wording, and it is indexable); only `TrackComplaintForm` ships JS.
 * ISR at 60s: an admin's save goes public within about a minute instead of
 * costing a gateway round-trip per visitor.
 *
 * "Agent sign in" appears twice — top-right header and an outlined button
 * below the hero — because at `text-xs text-white/50` in one corner it was
 * effectively invisible to the people who need it. Both stay quieter than the
 * accent-coloured track button: citizens are the primary audience here.
 */
export const revalidate = 60;

export default async function Home() {
  const content = await fetchLandingPage();
  const { colors } = content;

  // Palette as CSS variables so the client form (and everything below) can use
  // it without prop-drilling. Values are validated hex on both sides, which is
  // what makes interpolating them into `style` safe.
  const paletteVars = {
    "--ls-from": colors.from,
    "--ls-via": colors.via,
    "--ls-to": colors.to,
    "--ls-accent": colors.accent,
    "--ls-accent-to": colors.accentTo,
  } as React.CSSProperties;

  const extraSections: LandingSection[] = content.sections;
  const contact: LandingContactSection = content.contact;
  const hasContactDetails = Boolean(
    contact.email || contact.phone || contact.whatsapp || contact.address || contact.hours,
  );

  const signInLink = (
    <Link
      href="/login"
      className="rounded-lg border border-white/30 bg-white/10 px-4 py-2 text-sm font-semibold text-white shadow-sm backdrop-blur-sm transition hover:border-white/60 hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--ls-from)]"
    >
      {content.agentSignInLabel}
    </Link>
  );

  return (
    <div style={paletteVars} className="min-h-screen bg-white">
      {/* ---- Hero ---------------------------------------------------- */}
      <main
        className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6 pb-16 pt-28 text-white"
        style={{
          backgroundImage:
            "linear-gradient(to bottom right, var(--ls-from), var(--ls-via), var(--ls-to))",
        }}
      >
        {/* Decorative glows — same device as the login page's brand panel, so
            this reads as the same product, just brighter/higher-contrast for
            a public-facing "front door" rather than a staff work surface. */}
        <div
          aria-hidden
          className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full opacity-30 blur-3xl"
          style={{ backgroundColor: "var(--ls-to)" }}
        />
        <div
          aria-hidden
          className="pointer-events-none absolute -left-24 bottom-0 h-80 w-80 rounded-full opacity-25 blur-3xl"
          style={{ backgroundColor: "var(--ls-accent)" }}
        />
        <div
          aria-hidden
          className="pointer-events-none absolute bottom-1/3 right-1/4 h-64 w-64 rounded-full opacity-20 blur-3xl"
          style={{ backgroundColor: "var(--ls-accent-to)" }}
        />

        {/* Header sits absolutely so the hero below stays vertically centred. */}
        <header className="absolute inset-x-0 top-0 z-20 flex items-center justify-between gap-4 px-6 py-5 sm:px-8">
          <span className="flex items-center gap-2">
            {content.logoUrl ? (
              // Plain <img>, not next/image: the URL is admin-supplied and can
              // point at any tenant's host, which next/image would require
              // whitelisting in next.config at build time — exactly the
              // coupling this feature exists to remove.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={content.logoUrl}
                alt={content.brandName}
                className="h-8 w-auto max-w-[160px] object-contain"
              />
            ) : (
              <span className="text-sm font-semibold tracking-wide text-white/70">
                {content.brandName}
              </span>
            )}
          </span>
          {signInLink}
        </header>

        <div className="relative z-10 flex w-full max-w-xl flex-col items-center text-center">
          <h1
            className="bg-clip-text text-5xl font-extrabold tracking-tight text-transparent drop-shadow-sm sm:text-6xl"
            style={{
              backgroundImage:
                "linear-gradient(to right, var(--ls-to), var(--ls-accent), var(--ls-accent-to))",
            }}
          >
            {content.brandName}
          </h1>
          <p className="mt-3 text-lg text-white/90">{content.tagline}</p>
          <p className="mt-1 text-sm text-white/60">{content.subTagline}</p>

          <div className="mt-10 w-full rounded-2xl border border-white/15 bg-white/10 p-6 text-left shadow-2xl backdrop-blur-md sm:p-8">
            <h2 className="text-xl font-semibold text-white">{content.trackHeading}</h2>
            <p className="mt-1 text-sm text-white/70">{content.trackHelp}</p>
            <TrackComplaintForm
              placeholder={content.trackPlaceholder}
              buttonLabel={content.trackButtonLabel}
            />
          </div>

          <p className="mt-8 max-w-sm whitespace-pre-line text-sm text-white/60">
            {content.notFiledText}
          </p>

          <Link
            href="/login"
            className="mt-10 inline-flex items-center gap-2 rounded-full border border-white/40 px-6 py-2.5 text-sm font-semibold text-white transition hover:border-white hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--ls-from)]"
          >
            {content.agentSignInLabel} <span aria-hidden>→</span>
          </Link>
          <p className="mt-2 text-xs text-white/50">{content.agentSignInCaption}</p>
        </div>
      </main>

      {/* ---- About / How it works / Contact -------------------------- */}
      <section className="bg-slate-50 px-6 py-16 sm:py-20">
        <div className="mx-auto grid max-w-5xl gap-6 md:grid-cols-3">
          <InfoCard section={content.about} />
          <InfoCard section={content.howItWorks} />
          <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h2 className="text-lg font-semibold text-slate-900">{contact.heading}</h2>
            {contact.body && (
              <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-600">
                {contact.body}
              </p>
            )}
            {hasContactDetails && (
              <dl className="mt-4 space-y-2 text-sm">
                <ContactRow label="Email" value={contact.email} href={`mailto:${contact.email}`} />
                <ContactRow label="Phone" value={contact.phone} href={`tel:${contact.phone}`} />
                <ContactRow
                  label="WhatsApp"
                  value={contact.whatsapp}
                  href={`https://wa.me/${contact.whatsapp.replace(/\D/g, "")}`}
                />
                <ContactRow label="Address" value={contact.address} />
                <ContactRow label="Hours" value={contact.hours} />
              </dl>
            )}
          </div>
        </div>

        {extraSections.length > 0 && (
          <div className="mx-auto mt-6 grid max-w-5xl gap-6 md:grid-cols-3">
            {extraSections.map((section, i) => (
              <InfoCard key={`${section.heading}-${i}`} section={section} />
            ))}
          </div>
        )}
      </section>

      {/* ---- Footer -------------------------------------------------- */}
      <footer
        className="px-6 py-8 text-white/70"
        style={{ backgroundColor: "var(--ls-from)" }}
      >
        <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-4 text-sm sm:flex-row">
          <p className="text-center sm:text-left">{content.footerNote}</p>
          <nav className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2">
            {content.footerLinks.map((link, i) => (
              <a
                key={`${link.url}-${i}`}
                href={link.url}
                className="underline-offset-4 transition hover:text-white hover:underline"
              >
                {link.label}
              </a>
            ))}
            <Link href="/login" className="underline-offset-4 transition hover:text-white hover:underline">
              {content.agentSignInLabel}
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}

/** One About/How-it-works/extra card. Body is a text node — never HTML — so
 *  admin-authored copy cannot inject markup; `whitespace-pre-line` is what
 *  makes their paragraph breaks survive. */
function InfoCard({ section }: { section: LandingSection }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold text-slate-900">{section.heading}</h2>
      {section.body && (
        <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-600">
          {section.body}
        </p>
      )}
    </div>
  );
}

/** A contact line, rendered only when the admin filled it in — a blank field
 *  means "we don't offer this channel", not "show an empty row". */
function ContactRow({ label, value, href }: { label: string; value: string; href?: string }) {
  if (!value) return null;
  return (
    <div className="flex gap-2">
      <dt className="w-20 shrink-0 font-medium text-slate-500">{label}</dt>
      <dd className="text-slate-700">
        {href ? (
          <a href={href} className="text-slate-700 underline-offset-4 hover:underline">
            {value}
          </a>
        ) : (
          value
        )}
      </dd>
    </div>
  );
}
