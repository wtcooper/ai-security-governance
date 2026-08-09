import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import { fetchGatewayStatus } from "@/lib/api";
import "./globals.css";

/**
 * IBM Plex, in two voices from one superfamily.
 *
 * Chosen for its engineering heritage rather than its novelty: Plex was designed for technical
 * documentation and instrumentation, and its slightly squared terminals read as equipment
 * instead of as a startup landing page. Sans carries the interface; Mono carries every number,
 * model alias, metric key and hash — which in this app is most of the content.
 */
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI Security Governance",
  description:
    "Security evaluation and governance thresholds for AI assets: models, MCP servers, agent skills.",
};

/**
 * Gateway state, reduced to one honest dot in the header. It used to be a panel on the
 * landing page; a status light with a label is all a submitter needs, and everything else
 * about the gateway belongs on the pages that use it.
 */
async function GatewayPill() {
  const gateway = await fetchGatewayStatus();
  const reachable = gateway?.ok ?? false;
  return (
    <span
      className="flex items-center gap-1.5 text-[11px] text-muted"
      title={
        reachable
          ? `Model gateway reachable at ${gateway?.base_url}`
          : "Model gateway unreachable — no evaluation can run"
      }
    >
      <span
        aria-hidden="true"
        className={`inline-block h-1.5 w-1.5 rounded-full ${
          reachable ? "bg-pass" : "bg-block"
        }`}
      />
      Gateway
      <span className="sr-only">{reachable ? "reachable" : "unreachable"}</span>
    </span>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body>
        <header className="border-b border-rule bg-surface">
          <nav className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3.5">
            <Link href="/" className="flex items-center gap-2 text-ink">
              <ShieldCheck size={17} strokeWidth={2} aria-hidden="true" />
              <span className="text-[13px] font-semibold tracking-tight">
                AI Security Governance
              </span>
            </Link>
            <div className="flex items-center gap-5 text-[13px]">
              <Link href="/" className="text-muted transition-colors hover:text-ink">
                Evaluate
              </Link>
              <Link href="/evaluations" className="text-muted transition-colors hover:text-ink">
                Results
              </Link>
              <Link href="/benchmarks" className="text-muted transition-colors hover:text-ink">
                Benchmarks
              </Link>
              <Link href="/policies" className="text-muted transition-colors hover:text-ink">
                Policies
              </Link>
              <GatewayPill />
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
        <footer className="mx-auto max-w-5xl px-6 pb-10">
          <p className="border-t border-rule pt-4 text-[11px] text-faint">
            Security criteria only — acceptable use and compliance are assessed separately.
          </p>
        </footer>
      </body>
    </html>
  );
}
