import Link from "next/link";
import { fetchLeaderboard, fetchPolicy, type AssetType, type LeaderboardRow } from "@/lib/api";

const TABS: { slug: AssetType; label: string }[] = [
  { slug: "llm", label: "Foundation models" },
  { slug: "mcp", label: "MCP servers" },
  { slug: "skill", label: "Agent skills" },
];

const DECISION_STYLE: Record<string, string> = {
  auto_approve: "bg-pass/15 text-pass",
  needs_deep_testing: "bg-warn/15 text-warn",
  error: "bg-fail/15 text-fail",
};

const DECISION_LABEL: Record<string, string> = {
  auto_approve: "Auto-approve",
  needs_deep_testing: "Needs deep testing",
  error: "Error",
};

export default async function LeaderboardPage({
  searchParams,
}: {
  searchParams: Promise<{ type?: string }>;
}) {
  const { type } = await searchParams;
  const active: AssetType =
    type === "mcp" || type === "skill" || type === "llm" ? (type as AssetType) : "llm";

  const [rows, policy] = await Promise.all([fetchLeaderboard(active), fetchPolicy()]);

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Leaderboards</h1>
        <p className="text-sm text-muted">
          Latest evaluations and the decision each produced.
          {policy && ` Policy v${policy.version} (${policy.content_hash}).`}
        </p>
      </div>

      <nav className="flex gap-1 border-b border-edge">
        {TABS.map((tab) => (
          <Link
            key={tab.slug}
            href={`/leaderboard?type=${tab.slug}`}
            className={`px-3 py-2 text-sm ${
              tab.slug === active
                ? "border-b-2 border-accent text-white"
                : "text-muted hover:text-white"
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </nav>

      {active !== "llm" && (
        <p className="rounded border border-warn/40 bg-warn/10 px-4 py-3 text-sm text-warn">
          {active === "mcp" ? "MCP servers" : "Agent skills"} are gated on a severity rule
          rather than a score, and run in <strong>advisory mode</strong>: nothing here is
          auto-approved, because the rule has no false-positive baseline yet. The score column
          is a severity roll-up for ordering only.
        </p>
      )}

      {rows === null ? (
        <p className="text-sm text-fail">Could not reach the backend.</p>
      ) : rows.length === 0 ? (
        <p className="rounded border border-edge bg-surface px-4 py-6 text-sm text-muted">
          No evaluations yet.{" "}
          <Link href={`/evaluate/${active}`} className="text-accent hover:underline">
            Run one
          </Link>
          .
        </p>
      ) : (
        <Table rows={rows} />
      )}
    </div>
  );
}

function Table({ rows }: { rows: LeaderboardRow[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-edge">
      <table className="w-full min-w-[52rem] border-collapse text-sm">
        <thead className="bg-surface">
          <tr className="text-left text-xs text-muted">
            <th className="px-4 py-3 font-medium">Asset</th>
            <th className="px-4 py-3 font-medium">Decision</th>
            <th className="px-4 py-3 font-medium">Gates</th>
            <th className="px-4 py-3 font-medium">
              Score
              <span className="ml-1 font-normal normal-case">(display only)</span>
            </th>
            <th className="px-4 py-3 font-medium">Judge</th>
            <th className="px-4 py-3 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.run_id} className="border-t border-edge">
              <td className="px-4 py-3">
                <Link href={`/runs/${row.run_id}`} className="text-accent hover:underline">
                  {row.asset_name}
                </Link>
                <div className="font-mono text-[11px] text-muted">{row.identifier}</div>
              </td>
              <td className="px-4 py-3">
                {row.decision ? (
                  <span
                    className={`rounded px-2 py-0.5 text-xs ${
                      DECISION_STYLE[row.decision] ?? "bg-edge text-muted"
                    }`}
                  >
                    {DECISION_LABEL[row.decision] ?? row.decision}
                  </span>
                ) : (
                  <span className="text-xs text-muted">pending</span>
                )}
              </td>
              <td className="px-4 py-3 font-mono text-xs">
                {row.gates_passed}/{row.gates_total}
              </td>
              <td className="px-4 py-3 font-mono text-xs">
                {row.composite_score ?? "—"}
              </td>
              <td className="px-4 py-3 font-mono text-[11px] text-muted">
                {row.judge_model ?? "—"}
                {row.judge_refusal_rate != null && row.judge_refusal_rate > 0 && (
                  <div className="text-warn">
                    refused {(row.judge_refusal_rate * 100).toFixed(1)}%
                  </div>
                )}
              </td>
              <td className="px-4 py-3 text-xs text-muted">{row.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
