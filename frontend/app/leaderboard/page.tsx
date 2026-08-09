import Link from "next/link";
import { ChevronDown, ChevronRight, FlaskConical, Info } from "lucide-react";
import { fetchLeaderboard, fetchPolicy, type AssetType, type LeaderboardRow } from "@/lib/api";
import { PolicyPanel } from "../ui/policy-panel";
import { Term } from "../ui/term";
import { ASSET, DECISION, PENDING, TONE_TEXT, decisionFor } from "../ui/vocabulary";

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
          {policy?.classes?.[active] && (
            <>
              {" "}
              Governed by policy{" "}
              <span className="tnum">v{policy.classes[active].version}</span>{" "}
              <span className="tnum text-faint">({policy.classes[active].content_hash})</span>.
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

      <DecisionKey active={active} />
      <PolicyPanel assetType={active} />

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

/** What each decision means, per asset class. A plain <details> element: server-rendered,
 *  collapsed by default, no client JS — the explanation is there when needed and silent
 *  when not. */
function DecisionKey({ active }: { active: AssetType }) {
  const entries: { key: keyof typeof DECISION | "running"; text: string }[] =
    active === "llm"
      ? [
          {
            key: "auto_approve",
            text: "Every benchmark gate passed and the judge graded reliably. All benchmarks must actually be measured — a missing score counts as a failed gate, never a skipped one.",
          },
          {
            key: "needs_deep_testing",
            text: "One or more gates failed or were never measured. The asset is not rejected; it goes to formal deep testing instead of being waved through.",
          },
          {
            key: "error",
            text: "The run errored, or the judge refused or failed to grade too many samples for its scores to be trusted. Scores are recorded for inspection but no decision is emitted from them.",
          },
          {
            key: "running",
            text: "Benchmarks are still executing against the gateway.",
          },
        ]
      : [
          {
            key: "auto_approve",
            text: "The scan completed with no findings at a blocking severity. Only reachable once the severity rule leaves advisory mode.",
          },
          {
            key: "needs_deep_testing",
            text: "The scan found something at a blocking severity — or the rule is in advisory mode, where every result goes to human review regardless of findings.",
          },
          {
            key: "error",
            text: "The scanner failed to produce a verdict, so there is nothing to decide from.",
          },
          {
            key: "running",
            text: "The scanner is still analysing the submission.",
          },
        ];

  return (
    <details className="group rounded-card border border-rule bg-surface">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-[12px] font-medium text-muted transition-colors hover:text-ink [&::-webkit-details-marker]:hidden">
        <ChevronDown
          size={14}
          className="transition-transform group-open:rotate-180"
          aria-hidden="true"
        />
        How a decision is reached
      </summary>
      <div className="space-y-3 border-t border-rule px-4 py-4">
        <dl className="space-y-2.5">
          {entries.map(({ key, text }) => {
            const verdict = key === "running" ? PENDING : DECISION[key];
            const Icon = verdict.icon;
            return (
              <div key={key} className="flex gap-2.5">
                <Icon
                  size={14}
                  strokeWidth={2}
                  className={`mt-0.5 shrink-0 ${TONE_TEXT[verdict.tone]}`}
                  aria-hidden="true"
                />
                <div className="text-[12px] leading-relaxed">
                  <dt className={`inline font-medium ${TONE_TEXT[verdict.tone]}`}>
                    {verdict.label}.
                  </dt>{" "}
                  <dd className="inline text-muted">{text}</dd>
                </div>
              </div>
            );
          })}
        </dl>
        <p className="border-t border-rule pt-3 text-[12px] leading-relaxed text-muted">
          {active === "llm" ? (
            <>
              <strong className="font-medium text-ink">Gates</strong> counts benchmark gates
              passed out of gates required — the decision is made from these alone.{" "}
              <strong className="font-medium text-ink">Score</strong> is a weighted composite
              for ordering the table; it never influences the decision.{" "}
              <strong className="font-medium text-ink">Judge</strong> is the model that graded
              open-ended responses; if it left samples unresolved, that is shown because it
              weakens the measurement.
            </>
          ) : (
            <>
              <strong className="font-medium text-ink">Score</strong> is a severity roll-up of
              scanner findings, used only to order the table — the decision comes from the
              severity rule, never from this number.
            </>
          )}
        </p>
      </div>
    </details>
  );
}

function Table({ rows }: { rows: LeaderboardRow[] }) {
  const isLlm = rows[0]?.asset_type === "llm";
  return (
    <div className="overflow-x-auto rounded-card border border-rule bg-surface">
      <table className="w-full min-w-[52rem] border-collapse">
        <thead>
          <tr className="border-b border-rule">
            <th className="eyebrow px-5 py-2.5 text-left font-medium">Asset</th>
            <th className="eyebrow px-5 py-2.5 text-left font-medium">Decision</th>
            <th className="eyebrow px-5 py-2.5 text-left font-medium">Gates</th>
            {isLlm && (
              <th className="eyebrow px-5 py-2.5 text-left font-medium">
                <Term
                  label="n"
                  tip="Samples measured per benchmark (smallest–largest across the run's gated scores). A score over a handful of samples is a wiring check, not a measurement."
                />
              </th>
            )}
            <th className="eyebrow px-5 py-2.5 text-left font-medium">
              <Term
                label="Score"
                tip="Weighted composite of the gated benchmark scores, shown only when every benchmark was measured. Orders the table; never part of the decision."
              />{" "}
              <span className="normal-case tracking-normal">(display only)</span>
            </th>
            <th className="eyebrow px-5 py-2.5 text-left font-medium">Judge</th>
            <th className="eyebrow px-5 py-2.5 text-left font-medium">When</th>
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
                    <Icon
                      size={14}
                      strokeWidth={2}
                      className={verdict.spin ? "spinner" : undefined}
                      aria-hidden="true"
                    />
                    {verdict.label}
                  </span>
                </td>
                <td className="tnum px-5 py-3.5 text-[13px]">
                  {row.gates_passed}
                  <span className="text-faint">/{row.gates_total}</span>
                </td>
                {isLlm && (
                  <td className="px-5 py-3.5">
                    <span className="tnum text-[12px]">
                      {row.samples_min == null
                        ? "—"
                        : row.samples_min === row.samples_max
                          ? row.samples_min
                          : `${row.samples_min}–${row.samples_max}`}
                    </span>
                    {row.sample_override != null && (
                      <span
                        className="mt-0.5 flex items-center gap-1 text-[11px] font-medium text-warn"
                        title="Sample counts were overridden for this run; it is not policy-governed."
                      >
                        <FlaskConical size={11} aria-hidden="true" />
                        override
                      </span>
                    )}
                  </td>
                )}
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
                <td className="px-5 py-3.5">
                  <span className="tnum text-[11px] text-muted">
                    {new Date(row.started_at + "Z").toLocaleString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
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
