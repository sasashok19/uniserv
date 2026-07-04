import Link from "next/link";

export default function Home() {
  return (
    <main className="container flex min-h-screen flex-col items-center justify-center gap-4 py-16">
      <h1 className="text-4xl font-bold tracking-tight">UniServe</h1>
      <p className="text-muted-foreground">
        Multi-tenant AI-powered complaint &amp; feedback portal
      </p>
      <div className="flex gap-3">
        <Link href="/login" className="rounded-full border px-4 py-1 text-sm">
          Agent sign in
        </Link>
        <Link href="/status/ANON-TEST" className="rounded-full border px-4 py-1 text-sm">
          Track a complaint
        </Link>
      </div>
    </main>
  );
}
