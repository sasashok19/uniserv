import { gatewayBase } from "@/lib/gateway";
import { BASE as BADGE_BASE, statusBadgeStyle } from "@/lib/badges";

export const dynamic = "force-dynamic";

type PublicTicket = {
  ticketNumber: string;
  status: string;
  category: string | null;
  lastUpdated: string | null;
};

/** Plain-language "what happens next" per status, so a citizen doesn't have
 * to guess whose turn it is to act next. */
const NEXT_STEPS: Record<string, string> = {
  open: "Your complaint has been received and will be assigned to an agent shortly.",
  assigned: "An agent has been assigned and will begin reviewing your complaint.",
  in_progress: "Your complaint is actively being worked on.",
  pending_customer: "We're waiting for a response from you — please check your email or WhatsApp for our message.",
  resolved: "Your complaint has been resolved. Contact us if you have further questions.",
  closed: "This complaint is closed.",
  reopened: "Your complaint has been reopened and is being reviewed again.",
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

  const Brand = () => (
    <div className="mb-6 flex items-center gap-2">
      <span className="bg-gradient-to-r from-[#028090] to-[#02C39A] bg-clip-text text-xl font-extrabold tracking-tight text-transparent">
        UniServe
      </span>
    </div>
  );

  if (!data) {
    return (
      <main className="mx-auto max-w-xl p-8">
        <Brand />
        <h1 className="text-2xl font-bold text-slate-800">Complaint status</h1>
        <p className="mt-4 text-slate-600">
          No record found for reference <strong>{params.ref}</strong>.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col p-8">
      <Brand />
      <h1 className="text-2xl font-bold text-slate-800">Complaint status</h1>
      <p className="mt-1 text-sm text-slate-600">Reference: {data.ref}</p>

      {data.tickets.length === 0 ? (
        <p className="mt-6 text-slate-700">
          Your request has been received and is being registered. Please check
          back shortly for updates.
        </p>
      ) : (
        <ul className="mt-6 space-y-4">
          {data.tickets.map((t) => (
            <li key={t.ticketNumber} className="rounded-lg border p-4">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-800">{t.ticketNumber}</span>
                <span
                  className={`${BADGE_BASE} px-3 py-1 text-sm font-semibold`}
                  style={statusBadgeStyle(t.status)}
                >
                  {t.status.replace(/_/g, " ")}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-700">Category: {t.category ?? "—"}</p>
              {NEXT_STEPS[t.status] && (
                <p className="mt-2 text-sm text-slate-600">{NEXT_STEPS[t.status]}</p>
              )}
              <p className="mt-1 text-xs text-slate-600">
                Last updated: {t.lastUpdated ?? "—"}
              </p>
            </li>
          ))}
        </ul>
      )}

      <p className="mt-8 text-xs text-slate-600">
        Need help? Contact our support team quoting your reference number.
      </p>

      <footer className="mt-auto pt-10 text-center text-xs text-slate-400">
        Powered by UniServe
      </footer>
    </main>
  );
}
