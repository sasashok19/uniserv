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
      {/* Brand panel — hidden on small screens. Layered background: an
          optional hero illustration (public/backgrounds/login-hero.jpg) under
          a navy→teal overlay that keeps the text legible; if the image is
          absent the overlay + glow blobs render as a colourful gradient on
          their own (a missing CSS background-image fails silently). */}
      <aside className="relative hidden w-2/5 flex-col justify-between overflow-hidden p-10 lg:flex">
        <div
          aria-hidden
          className="absolute inset-0 bg-[#0D1B2A]"
          style={{
            backgroundImage:
              "linear-gradient(165deg, rgba(13,27,42,0.94) 0%, rgba(13,27,42,0.82) 35%, rgba(2,128,144,0.72) 70%, rgba(2,195,154,0.55) 100%), url('/backgrounds/login-hero.jpg')",
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
        />
        {/* Decorative glow — colour even without the image. */}
        <div aria-hidden className="absolute -right-24 -top-24 h-80 w-80 rounded-full bg-[#02C39A]/25 blur-3xl" />
        <div aria-hidden className="absolute -left-20 bottom-16 h-72 w-72 rounded-full bg-[#F4A261]/25 blur-3xl" />
        <div aria-hidden className="absolute left-1/3 top-1/2 h-56 w-56 rounded-full bg-[#028090]/30 blur-3xl" />

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

      {/* Sign-in panel — soft wash behind a white card, matching the app's panel style. */}
      <section className="flex flex-1 flex-col justify-center bg-gradient-to-br from-[#E8F6F8] via-white to-[#FFF3E8] p-8">
        <div className="mx-auto w-full max-w-sm rounded-xl border bg-white p-8 shadow-lg">
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
