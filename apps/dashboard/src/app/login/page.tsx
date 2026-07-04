"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** Login page (Feature 12). Posts to the dashboard's own /api/auth/login route. */
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
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center p-8">
      <h1 className="text-2xl font-bold">UniServe</h1>
      <p className="mb-6 text-sm text-muted-foreground">Agent sign in</p>
      <form onSubmit={submit} className="space-y-3">
        <input
          className="w-full rounded border p-2 text-sm"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
        />
        <input
          className="w-full rounded border p-2 text-sm"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
        />
        {error && <p className="text-sm text-red-500">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded bg-black p-2 text-sm text-white disabled:opacity-50"
        >
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
