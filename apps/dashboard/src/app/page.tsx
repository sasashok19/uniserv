"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Public landing page (Feature 12). Previously a bare placeholder whose
 * "Track a complaint" link pointed at a hardcoded example ref (`ANON-TEST`)
 * — there was no real way for a citizen to look up their OWN complaint.
 * This is now a working search that submits to `/status/{ref}`
 * (`PublicStatusResource` accepts a `TKT-XXXXX` ticket number, an
 * `ANON-XXXX` reference, or an email — NOT a phone number, so the copy
 * below must not imply that works). "Agent sign in" is kept as a small,
 * secondary link — citizens are the primary audience of this page, staff
 * are not.
 */
export default function Home() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");

  function trackComplaint(e: React.FormEvent) {
    e.preventDefault();
    const value = query.trim();
    if (!value) {
      setError("Enter your reference number or email to continue.");
      return;
    }
    setError("");
    router.push(`/status/${encodeURIComponent(value)}`);
  }

  return (
    <main className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-gradient-to-br from-[#0D1B2A] via-[#1B3A52] to-[#028090] px-6 py-16 text-white">
      {/* Decorative glows — same device as the login page's brand panel, so
          this reads as the same product, just brighter/higher-contrast for
          a public-facing "front door" rather than a staff work surface. */}
      <div aria-hidden className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full bg-[#02C39A]/30 blur-3xl" />
      <div aria-hidden className="pointer-events-none absolute -left-24 bottom-0 h-80 w-80 rounded-full bg-[#F4A261]/25 blur-3xl" />
      <div aria-hidden className="pointer-events-none absolute right-1/4 bottom-1/3 h-64 w-64 rounded-full bg-[#E07B54]/20 blur-3xl" />

      <div className="relative z-10 flex w-full max-w-xl flex-col items-center text-center">
        <h1 className="bg-gradient-to-r from-[#02C39A] via-[#F4A261] to-[#E07B54] bg-clip-text text-5xl font-extrabold tracking-tight text-transparent drop-shadow-sm sm:text-6xl">
          UniServe
        </h1>
        <p className="mt-3 text-lg text-white/90">The complaint that gets heard.</p>
        <p className="mt-1 text-sm text-white/60">
          Multi-tenant AI-powered complaint &amp; feedback portal
        </p>

        <div className="mt-10 w-full rounded-2xl border border-white/15 bg-white/10 p-6 text-left shadow-2xl backdrop-blur-md sm:p-8">
          <h2 className="text-xl font-semibold text-white">Track your complaint</h2>
          <p className="mt-1 text-sm text-white/70">
            Enter your ticket number (e.g. TKT-00042), your ANON-XXXX
            reference, or the email address you wrote in from.
          </p>
          <form onSubmit={trackComplaint} className="mt-4 flex flex-col gap-2 sm:flex-row" noValidate>
            <input
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                if (error) setError("");
              }}
              placeholder="TKT-00042, ANON-1234, or you@example.com"
              aria-label="Ticket number, reference number, or email"
              className="w-full rounded-lg border border-white/20 bg-white/95 px-4 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#02C39A]"
            />
            <button
              type="submit"
              className="rounded-lg bg-gradient-to-r from-[#F4A261] to-[#E07B54] px-6 py-2.5 text-sm font-semibold text-white shadow-lg transition-transform active:scale-[0.97] sm:shrink-0"
            >
              Track complaint
            </button>
          </form>
          {error && <p className="mt-2 text-sm text-[#FFD9C7]">{error}</p>}
        </div>

        <p className="mt-8 max-w-sm text-sm text-white/60">
          Haven&apos;t filed a complaint yet? Reach us by{" "}
          <span className="font-semibold text-white/85">Email</span> or{" "}
          <span className="font-semibold text-white/85">WhatsApp</span> and
          we&apos;ll take it from there.
        </p>

        <Link
          href="/login"
          className="mt-10 text-xs font-medium text-white/50 underline-offset-4 transition hover:text-white/85 hover:underline"
        >
          Agent sign in →
        </Link>
      </div>
    </main>
  );
}
