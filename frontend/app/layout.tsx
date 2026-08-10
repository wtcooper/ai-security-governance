import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import { ShieldCheck } from "lucide-react";
import { fetchGatewayStatus } from "@/lib/api";
import { NavLinks } from "./ui/nav-links";
import "./globals.css";

/**
 * Two voices: Inter carries the interface, JetBrains Mono carries every number, model
 * alias, metric key and hash — which in this app is most of the content. Both are variable
 * fonts, so weights are free rather than separate downloads.
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI Security Governance",
  description:
    "Security evaluation and governance thresholds for AI assets: models, MCP servers, agent skills.",
};

/**
 * Gateway state, reduced to one honest light on the command bar. It used to be a panel on
 * the landing page; a status light with a label is all a submitter needs, and everything
 * else about the gateway belongs on the pages that use it.
 */
async function GatewayPill() {
  const gateway = await fetchGatewayStatus();
  const reachable = gateway?.ok ?? false;
  return (
    <span
      className="tnum flex items-center gap-1.5 rounded-full border border-white/18 px-2.5 py-1 text-[10.5px] tracking-wide text-carbon-muted"
      title={
        reachable
          ? `Model gateway reachable at ${gateway?.base_url}`
          : "Model gateway unreachable — no evaluation can run"
      }
    >
      <span
        aria-hidden="true"
        className={`inline-block h-1.5 w-1.5 rounded-full ${
          reachable ? "bg-pass-bright" : "bg-block-bright"
        }`}
      />
      Gateway
      <span className="sr-only">{reachable ? "reachable" : "unreachable"}</span>
    </span>
  );
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body>
        {/* The command bar: dark chrome holds the tools, the record below stays on paper. */}
        <header className="bg-carbon text-carbon-ink">
          <nav className="mx-auto flex max-w-5xl items-center justify-between gap-6 px-6 py-3">
            <Link href="/" className="flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="grid h-[22px] w-[22px] place-items-center rounded-[5px] bg-accent"
              >
                <ShieldCheck size={13} strokeWidth={2.25} className="text-white" />
              </span>
              <span className="text-[13.5px] font-semibold tracking-tight">
                AI Security Governance
              </span>
            </Link>
            <div className="flex flex-1 items-center gap-0.5">
              <NavLinks />
            </div>
            <GatewayPill />
          </nav>
        </header>
        {/* The keel: a short cobalt strike under the brand — the accent's one structural use. */}
        <div aria-hidden="true" className="h-0.5 bg-[#22262d]">
          <div className="h-full w-[220px] bg-accent" />
        </div>
        <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
        <footer className="mx-auto max-w-5xl px-6 pb-10">
          <p className="border-t border-rule pt-4 text-[11px] text-faint">
            Security criteria only. AI acceptable use and compliance belong to a broader
            evaluation alongside this one.
          </p>
        </footer>
      </body>
    </html>
  );
}
