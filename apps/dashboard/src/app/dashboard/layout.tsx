/**
 * Shared backdrop for every /dashboard route (queue + ticket detail): a soft
 * teal→gold gradient wash with an OPTIONAL image layer. Drop a file at
 * `public/backgrounds/app-wash.jpg` and it appears behind a strong white veil
 * (panels stay perfectly readable); if the file is absent the CSS gradient
 * alone renders — a missing background-image URL fails silently by design.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="min-h-screen bg-[#F8FAFC]"
      style={{
        // The veil IS the colour wash (pale teal → off-white → warm gold), so
        // the page is colourful even before the image exists underneath it.
        backgroundImage:
          "linear-gradient(135deg, rgba(232,246,248,0.92) 0%, rgba(248,250,252,0.88) 45%, rgba(255,243,232,0.92) 100%), url('/backgrounds/app-wash.jpg')",
        backgroundSize: "cover",
        backgroundPosition: "center",
        backgroundAttachment: "fixed",
      }}
    >
      {children}
    </div>
  );
}
