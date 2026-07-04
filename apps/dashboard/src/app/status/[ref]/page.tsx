import { gatewayBase } from "@/lib/gateway";

export const dynamic = "force-dynamic";

type PublicTicket = {
  ticketNumber: string;
  status: string;
  category: string | null;
  lastUpdated: string | null;
};

type StatusData = {
  ref: string;
  isAnonymous: boolean;
  tickets: PublicTicket[];
};

async function fetchStatus(ref: string): Promise<StatusData | null> {
  const resp = await fetch(
    `${gatewayBase()}/api/v1/public/status/${encodeURIComponent(ref)}`,
    { cache: "no-store" },
  );
  if (!resp.ok) return null;
  return resp.json();
}

export async function generateMetadata({ params }: { params: { ref: string } }) {
  return { title: `Complaint status — ${params.ref}` };
}

/** Public citizen portal (Feature 12) — SSR, no authentication required. */
export default async function StatusPage({ params }: { params: { ref: string } }) {
  const data = await fetchStatus(params.ref);

  if (!data) {
    return (
      <main className="mx-auto max-w-xl p-8">
        <h1 className="text-2xl font-bold">Complaint status</h1>
        <p className="mt-4 text-muted-foreground">
          No record found for reference <strong>{params.ref}</strong>.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="text-2xl font-bold">Complaint status</h1>
      <p className="mt-1 text-sm text-muted-foreground">Reference: {data.ref}</p>

      {data.tickets.length === 0 ? (
        <p className="mt-6">
          Your request has been received and is being registered. Please check
          back shortly for updates.
        </p>
      ) : (
        <ul className="mt-6 space-y-4">
          {data.tickets.map((t) => (
            <li key={t.ticketNumber} className="rounded-lg border p-4">
              <div className="flex items-center justify-between">
                <span className="font-semibold">{t.ticketNumber}</span>
                <span className="rounded-full border px-2 py-0.5 text-xs uppercase">
                  {t.status}
                </span>
              </div>
              <p className="mt-2 text-sm">Category: {t.category ?? "—"}</p>
              <p className="text-xs text-muted-foreground">
                Last updated: {t.lastUpdated ?? "—"}
              </p>
            </li>
          ))}
        </ul>
      )}

      <p className="mt-8 text-xs text-muted-foreground">
        Need help? Contact our support team quoting your reference number.
      </p>
    </main>
  );
}
