"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import AnnouncementTicker from "@/components/announcements/AnnouncementTicker";
import NewsWidget from "@/components/news/NewsWidget";

/**
 * Login page (Feature 12, reskinned per UI_REVAMP_v2 §A4): split layout — navy
 * brand panel (tagline, BBC Tamil headlines, public announcement ticker) and
 * the sign-in card. The form's submit logic is unchanged from the original.
 */
export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@tneb.demo");
  const [password, setPassword] = useState("Admin@123");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const resp = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    setLoading(false);
    if (resp.ok) {
      router.push("/dashboard");
    } else {
      setError("Invalid email or password");
    }
  }

  return (
    <main className="flex min-h-screen">
      {/* Brand panel — hidden on small screens. Deliberately IMAGE-FREE: a
          calm navy gradient (plus two very faint glows) so the headlines and
          announcement ticker stay highly readable. */}
      <aside className="relative hidden w-2/5 flex-col justify-between overflow-hidden bg-gradient-to-b from-[#0D1B2A] via-[#0D1B2A] to-[#1B3A52] p-10 lg:flex">
        <div aria-hidden className="absolute -right-28 -top-28 h-72 w-72 rounded-full bg-[#028090]/15 blur-3xl" />
        <div aria-hidden className="absolute -left-24 bottom-10 h-64 w-64 rounded-full bg-[#F4A261]/10 blur-3xl" />

        <div className="relative">
          <h1 className="bg-gradient-to-r from-[#02C39A] to-[#E8F6F8] bg-clip-text text-4xl font-extrabold text-transparent drop-shadow">
            UniServe
          </h1>
          <p className="mt-2 text-sm text-white/80">The complaint that gets heard.</p>
        </div>
        <div className="relative my-8 flex-1 overflow-hidden py-8">
          <NewsWidget />
        </div>
        <div className="relative">
          <AnnouncementTicker />
        </div>
      </aside>

      {/* Sign-in panel — the hero image lives HERE (public/backgrounds/
          login-hero.jpg) under a light veil, with an extra white radial pool
          behind the centred card so the form is always readable; if the image
          is absent the veil + wash render as a soft gradient on their own. */}
      <section
        className="relative flex flex-1 flex-col justify-center overflow-hidden bg-gradient-to-br from-[#E8F6F8] via-white to-[#FFF3E8] p-8"
        style={{
          backgroundImage:
            "radial-gradient(ellipse 46rem 34rem at center, rgba(255,255,255,0.88) 0%, rgba(255,255,255,0.55) 45%, rgba(255,255,255,0) 75%), " +
            "linear-gradient(135deg, rgba(232,246,248,0.66) 0%, rgba(248,250,252,0.55) 50%, rgba(255,243,232,0.66) 100%), " +
            "url('/backgrounds/login-hero.jpg')",
          backgroundSize: "cover, cover, cover",
          backgroundPosition: "center",
        }}
      >
        <div className="mx-auto w-full max-w-sm rounded-xl border bg-white p-8 shadow-xl ring-1 ring-black/5">
          <h1 className="text-2xl font-bold lg:hidden">UniServe</h1>
          <h2 className="hidden text-xl font-semibold text-slate-800 lg:block">Welcome back</h2>
          <p className="mb-6 text-sm text-muted-foreground">Agent sign in</p>
          <form onSubmit={submit} className="space-y-3">
            <input
              className="w-full rounded border p-2 text-sm focus:border-[#028090] focus:outline-none"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email"
              disabled={loading}
            />
            <input
              className="w-full rounded border p-2 text-sm focus:border-[#028090] focus:outline-none"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              disabled={loading}
            />
            {error && <p className="rounded border border-red-200 bg-red-50 p-2 text-sm text-red-600">{error}</p>}
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded bg-gradient-to-r from-[#028090] to-[#02C39A] p-2 text-sm font-semibold text-white disabled:opacity-50"
            >
              {loading ? "Signing in…" : "Sign in"}
            </button>
          </form>
          {/* Ticker is styled for dark surfaces — give the mobile copy a navy backdrop. */}
          <div className="mt-6 rounded-lg bg-[#0D1B2A] p-1 lg:hidden">
            <AnnouncementTicker />
          </div>
        </div>
      </section>
    </main>
  );
}
