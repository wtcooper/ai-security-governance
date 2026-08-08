import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Security Governance",
  description:
    "Security evaluation and governance thresholds for AI assets: models, MCP servers, agent skills.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="border-b border-edge">
          <nav className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
            <Link href="/" className="text-sm font-semibold tracking-tight">
              AI Security Governance
            </Link>
            <div className="flex gap-6 text-sm text-muted">
              <Link href="/" className="hover:text-white">
                Evaluate
              </Link>
              <Link href="/leaderboard" className="hover:text-white">
                Leaderboards
              </Link>
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
      </body>
    </html>
  );
}
