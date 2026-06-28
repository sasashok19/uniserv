export default function Home() {
  return (
    <main className="container flex min-h-screen flex-col items-center justify-center gap-4 py-16">
      <h1 className="text-4xl font-bold tracking-tight">UniServe</h1>
      <p className="text-muted-foreground">
        Multi-tenant AI-powered complaint &amp; feedback portal
      </p>
      <span className="rounded-full border px-3 py-1 text-sm">
        Phase 1 scaffold — dashboard is healthy
      </span>
      {/* PHASE_1: Analytics, Ticket Queue, and Administration tabs are built in 12_AGENT_DASHBOARD. */}
    </main>
  );
}
