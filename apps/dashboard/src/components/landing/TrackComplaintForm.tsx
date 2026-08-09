"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * The landing page's complaint lookup (Feature 12). Split out of `page.tsx`
 * when that page became a server component (Feature 25): the surrounding copy
 * is tenant-configurable and fetched server-side, but this box needs client
 * state, so only this much ships as JS.
 *
 * Submits to `/status/{value}` — `PublicStatusResource` accepts a `TKT-XXXXX`
 * ticket number, an `ANON-XXXX` reference, or an email, but NOT a phone
 * number, so the configurable help text above it must not imply that works.
 */
export default function TrackComplaintForm({
  placeholder,
  buttonLabel,
}: {
  placeholder: string;
  buttonLabel: string;
}) {
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
    <>
      <form onSubmit={trackComplaint} className="mt-4 flex flex-col gap-2 sm:flex-row" noValidate>
        <input
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            if (error) setError("");
          }}
          placeholder={placeholder}
          aria-label="Ticket number, reference number, or email"
          className="w-full rounded-lg border border-white/20 bg-white/95 px-4 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ls-to)]"
        />
        <button
          type="submit"
          style={{
            backgroundImage: "linear-gradient(to right, var(--ls-accent), var(--ls-accent-to))",
          }}
          className="rounded-lg px-6 py-2.5 text-sm font-semibold text-white shadow-lg transition-transform active:scale-[0.97] sm:shrink-0"
        >
          {buttonLabel}
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-[#FFD9C7]">{error}</p>}
    </>
  );
}
