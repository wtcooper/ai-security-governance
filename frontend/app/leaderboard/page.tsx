import Link from "next/link";
import { ChevronRight, Info } from "lucide-react";
import { fetchLeaderboard, fetchPolicy, type AssetType, type LeaderboardRow } from "@/lib/api";
import { ASSET, TONE_TEXT, decisionFor } from "../ui/vocabulary";

const TABS: AssetType[] = ["llm", "mcp", "skill"];

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
    <div className="space-y-8">
      <section className="space-y-2">
        <h1 className="text-[26px] font-semibold leading-tight tracking-tight">Results</h1>
        <p className="text-[13.5px] text-muted">
          Every evaluation and the decision it produced.
          {policy && (
            <>
              {" "}
              Policy <span className="tnum">v{policy.version}</span>{" "}
              <span className="tnum text-faint">({policy.content_hash})</span>.
            </>
          )}
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

      {active !== "llm" && scanner?.mode === "advisory" && (
        <p className="flex gap-2 rounded-card border border-rule bg-surface px-4 py-3 text-[12px] leading-relaxed text-muted">
          <Info size={14} className="mt-px shrink-0 text-warn" aria-hidden="true" />
          <span>
            Gated on a severity rule rather than a score, and running in{" "}
            <strong className="font-medium text-ink">advisory mode</strong>: nothing here is
            auto-approved, because the rule has no false-positive baseline yet. The score column
            is a severity roll-up for ordering only.
          </span>
        </p>
      )}

      {rows === null ? (
        <p className="text-[13px] text-block">Could not reach the backend.</p>
      ) : rows.length === 0 ? (
        <p className="rounded-card border border-rule bg-surface px-5 py-8 text-center text-[13px] text-muted">
          No evaluations yet.{" "}
          <Link href={`/evaluate/${active}`} className="font-medium text-ink underline">
            Run one
          </Link>
        </p>
      ) : (
        <Table rows={rows} />
      )}
    </div>
  );
}

function Table({ rows }: { rows: LeaderboardRow[] }) {
  return (
    <div className="overflow-x-auto rounded-card border border-rule bg-surface">
      <table className="w-full min-w-[46rem] border-collapse">
        <thead>
          <tr className="border-b border-rule">
            <th className="eyebrow px-5 py-2.5 text-left font-medium">Asset</th>
            <th className="eyebrow px-5 py-2.5 text-left font-medium">Decision</th>
            <th className="eyebrow px-5 py-2.5 text-left font-medium">Gates</th>
            <th className="eyebrow px-5 py-2.5 text-left font-medium">
              Score <span className="normal-case tracking-normal">(display only)</span>
            </th>
            <th className="eyebrow px-5 py-2.5 text-left font-medium">Judge</th>
            <th className="w-8" />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const verdict = decisionFor(row.decision, row.status);
            const Icon = verdict.icon;
            return (
              <tr key={row.run_id} className="group border-b border-rule last:border-0">
                <td className="px-5 py-3.5">
                  <Link href={`/runs/${row.run_id}`} className="block">
                    <span className="text-[13px] font-medium group-hover:underline">
                      {row.asset_name}
                    </span>
                    <span className="tnum mt-0.5 block text-[11px] text-faint">
                      {row.identifier}
                    </span>
                  </Link>
                </td>
                <td className="px-5 py-3.5">
                  <span
                    className={`flex items-center gap-1.5 text-[12px] font-medium ${
                      TONE_TEXT[verdict.tone]
                    }`}
                  >
                    <Icon size={14} strokeWidth={2} aria-hidden="true" />
                    {verdict.label}
                  </span>
                </td>
                <td className="tnum px-5 py-3.5 text-[13px]">
                  {row.gates_passed}
                  <span className="text-faint">/{row.gates_total}</span>
                </td>
                <td className="tnum px-5 py-3.5 text-[13px]">
                  {row.composite_score ?? <span className="text-faint">—</span>}
                </td>
                <td className="px-5 py-3.5">
                  <span className="tnum text-[11px] text-muted">{row.judge_model ?? "—"}</span>
                  {row.judge_unresolved_rate != null && row.judge_unresolved_rate > 0 && (
                    <span className="tnum mt-0.5 block text-[11px] text-warn">
                      {(row.judge_unresolved_rate * 100).toFixed(0)}% unresolved
                    </span>
                  )}
                </td>
                <td className="px-2">
                  <Link href={`/runs/${row.run_id}`} aria-label={`Open ${row.asset_name}`}>
                    <ChevronRight
                      size={15}
                      className="text-faint transition-colors group-hover:text-ink"
                      aria-hidden="true"
                    />
                  </Link>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
