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
      {/* Brand panel — hidden on small screens. */}
      <aside className="hidden w-2/5 flex-col justify-between bg-[#0D1B2A] p-10 lg:flex">
        <div>
          <h1 className="bg-gradient-to-r from-[#028090] to-[#02C39A] bg-clip-text text-3xl font-extrabold text-transparent">
            UniServe
          </h1>
          <p className="mt-2 text-sm text-white/70">The complaint that gets heard.</p>
        </div>
        <div className="my-8 flex-1 overflow-hidden py-8">
          <NewsWidget />
        </div>
        <AnnouncementTicker />
      </aside>

      {/* Sign-in panel. */}
      <section className="flex flex-1 flex-col justify-center bg-white p-8">
        <div className="mx-auto w-full max-w-sm">
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
