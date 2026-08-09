import Link from "next/link";
import { BookOpen, Info, Plus } from "lucide-react";
import { fetchLeaderboard, fetchPolicy, type AssetType } from "@/lib/api";
import { ASSET } from "../ui/vocabulary";
import { ResultsTable } from "./results-table";

const TABS: AssetType[] = ["llm", "mcp", "skill"];

/**
 * Completed evaluations for one asset class.
 *
 * The page answers three things in order: what has been evaluated (the table), how those
 * decisions are made (a link to the criteria page), and how to evaluate something new (a
 * link to the form). Everything explanatory that used to sit in collapsed accordions now
 * lives on its own page — a governance record should not hide its own methodology behind a
 * disclosure triangle.
 */
export default async function LeaderboardPage({
  searchParams,
}: {
  searchParams: Promise<{ type?: string }>;
}) {
  const { type } = await searchParams;
  const active: AssetType =
    type === "mcp" || type === "skill" || type === "llm" ? (type as AssetType) : "llm";

  const [rows, policy] = await Promise.all([fetchLeaderboard(active), fetchPolicy()]);
  const scanner = policy?.scanner?.[active];

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h1 className="text-[26px] font-semibold leading-tight tracking-tight">
          {ASSET[active].label} evaluations
        </h1>
        <p className="text-[13.5px] text-muted">
          Every completed evaluation for this asset class and the decision it produced.
        </p>
      </section>

      <nav className="flex gap-6 border-b border-rule">
        {TABS.map((slug) => {
          const Icon = ASSET[slug].icon;
          const isActive = slug === active;
          return (
            <Link
              key={slug}
              href={`/leaderboard?type=${slug}`}
              className={`-mb-px flex items-center gap-1.5 border-b-2 pb-2.5 text-[13px] transition-colors ${
                isActive
                  ? "border-ink font-medium text-ink"
                  : "border-transparent text-muted hover:text-ink"
              }`}
            >
              <Icon size={14} strokeWidth={1.75} aria-hidden="true" />
              {ASSET[slug].label}
            </Link>
          );
        })}
      </nav>

      <div className="flex flex-wrap gap-2">
        <Link
          href={`/criteria/${active}`}
          className="inline-flex items-center gap-2 rounded border border-rule bg-surface px-3.5 py-2 text-[13px] font-medium transition-colors hover:border-ink"
        >
          <BookOpen size={14} strokeWidth={2} aria-hidden="true" />
          Evaluation criteria
        </Link>
        <Link
          href={`/evaluate/${active}`}
          className="inline-flex items-center gap-2 rounded bg-ink px-3.5 py-2 text-[13px] font-medium text-paper transition-opacity hover:opacity-90"
        >
          <Plus size={14} strokeWidth={2.5} aria-hidden="true" />
          New evaluation
        </Link>
      </div>

      {active !== "llm" && scanner?.mode === "advisory" && (
        <p className="flex gap-2 rounded-card border border-rule bg-surface px-4 py-3 text-[12px] leading-relaxed text-muted">
          <Info size={14} className="mt-px shrink-0 text-warn" aria-hidden="true" />
          <span>
            Gated on a severity rule rather than a score, and running in{" "}
            <strong className="font-medium text-ink">advisory mode</strong>: nothing here is
            auto-approved, because the rule has no false-positive baseline yet. The score
            column is a severity roll-up for ordering only.
          </span>
        </p>
      )}

      {rows === null ? (
        <p className="text-[13px] text-block">Could not reach the backend.</p>
      ) : rows.length === 0 ? (
        <div className="rounded-card border border-rule bg-surface px-5 py-10 text-center">
          <p className="text-[13px] text-muted">
            No {ASSET[active].label.toLowerCase()} evaluations yet.
          </p>
          <Link
            href={`/evaluate/${active}`}
            className="mt-3 inline-flex items-center gap-2 rounded bg-ink px-3.5 py-2 text-[13px] font-medium text-paper transition-opacity hover:opacity-90"
          >
            <Plus size={14} strokeWidth={2.5} aria-hidden="true" />
            Run the first one
          </Link>
        </div>
      ) : (
        <ResultsTable rows={rows} />
      )}
    </div>
  );
}
