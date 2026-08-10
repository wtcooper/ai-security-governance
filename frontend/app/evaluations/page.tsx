import Link from "next/link";
import { BookOpen, Plus } from "lucide-react";
import { fetchEvaluations, type AssetType } from "@/lib/api";
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
export default async function EvaluationsPage({
  searchParams,
}: {
  searchParams: Promise<{ type?: string }>;
}) {
  const { type } = await searchParams;
  const active: AssetType =
    type === "mcp" || type === "skill" || type === "llm" ? (type as AssetType) : "llm";

  const rows = await fetchEvaluations(active);

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
              href={`/evaluations?type=${slug}`}
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
          className="inline-flex items-center gap-2 rounded-md bg-accent px-3.5 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90"
        >
          <Plus size={14} strokeWidth={2.5} aria-hidden="true" />
          New evaluation
        </Link>
      </div>

      {rows === null ? (
        <p className="text-[13px] text-block">Could not reach the backend.</p>
      ) : rows.length === 0 ? (
        <div className="rounded-card border border-rule bg-surface px-5 py-10 text-center">
          <p className="text-[13px] text-muted">
            No {ASSET[active].sentence} evaluations yet.
          </p>
          <Link
            href={`/evaluate/${active}`}
            className="mt-3 inline-flex items-center gap-2 rounded-md bg-accent px-3.5 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90"
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
