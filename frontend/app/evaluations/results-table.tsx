"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronRight, FlaskConical, Search } from "lucide-react";
import type { EvaluationRow } from "@/lib/api";
import { TONE_TEXT, decisionFor, type Tone } from "../ui/vocabulary";

/**
 * The evaluations table.
 *
 * Four columns, because four things distinguish one evaluation from another at a glance: what
 * was evaluated, what it scored, which policy judged it, and when. The verdict is carried by
 * the row's colour and an icon beside the asset name rather than a column of its own — it is
 * the thing the eye should land on first, and a coloured word in the fourth column is not
 * that. Gates, judge and sample detail live on the run page, one click away.
 *
 * Sorting and filtering are client-side: these are tens of rows, not thousands, so a round
 * trip per sort would add latency to buy nothing.
 */

type SortKey = "asset" | "score" | "policy" | "date";

const TONE_ROW: Record<Tone, string> = {
  pass: "bg-pass-wash",
  warn: "bg-warn-wash",
  block: "bg-block-wash",
  neutral: "bg-surface",
};

const TONE_ACCENT: Record<Tone, string> = {
  pass: "border-l-pass",
  warn: "border-l-warn",
  block: "border-l-block",
  neutral: "border-l-rule-strong",
};

export function ResultsTable({ rows }: { rows: EvaluationRow[] }) {
  const [query, setQuery] = useState("");
  const [decisionFilter, setDecisionFilter] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("date");
  const [ascending, setAscending] = useState(false);

  // Counts drive the legend, and the legend doubles as the filter — one control, so a reader
  // never has to learn that the colours and the filters are the same vocabulary.
  const counts = useMemo(() => {
    const acc: Record<string, number> = {};
    for (const row of rows) {
      const label = decisionFor(row.decision, row.status).label;
      acc[label] = (acc[label] ?? 0) + 1;
    }
    return acc;
  }, [rows]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const filtered = rows.filter((row) => {
      if (decisionFilter && decisionFor(row.decision, row.status).label !== decisionFilter) {
        return false;
      }
      if (!needle) return true;
      return (
        row.asset_name.toLowerCase().includes(needle) ||
        row.identifier.toLowerCase().includes(needle)
      );
    });

    const direction = ascending ? 1 : -1;
    return [...filtered].sort((a, b) => {
      switch (sortKey) {
        case "asset":
          return direction * a.asset_name.localeCompare(b.asset_name);
        case "score":
          // Rows without a score sort last regardless of direction: "no score" is an absence,
          // not a low value, and ranking it as zero would read as a bad result.
          if (a.composite_score == null && b.composite_score == null) return 0;
          if (a.composite_score == null) return 1;
          if (b.composite_score == null) return -1;
          return direction * (a.composite_score - b.composite_score);
        case "policy":
          return direction * (Number(a.policy_version ?? 0) - Number(b.policy_version ?? 0));
        default:
          return direction * (a.started_at < b.started_at ? -1 : 1);
      }
    });
  }, [rows, query, decisionFilter, sortKey, ascending]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setAscending(!ascending);
    } else {
      setSortKey(key);
      // Names read best A–Z; numbers and dates read best highest/newest first.
      setAscending(key === "asset");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-center gap-2">
          {Object.entries(counts).map(([label, count]) => {
            const sample = rows.find(
              (row) => decisionFor(row.decision, row.status).label === label,
            )!;
            const verdict = decisionFor(sample.decision, sample.status);
            const Icon = verdict.icon;
            const isActive = decisionFilter === label;
            return (
              <button
                key={label}
                onClick={() => setDecisionFilter(isActive ? null : label)}
                aria-pressed={isActive}
                className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  isActive
                    ? "border-accent bg-accent text-white"
                    : `border-rule ${TONE_TEXT[verdict.tone]} hover:border-ink`
                }`}
              >
                <Icon size={11} strokeWidth={2.5} aria-hidden="true" />
                {label}
                <span className={isActive ? "text-white/70" : "text-faint"}>{count}</span>
              </button>
            );
          })}
        </div>

        <label className="ml-auto flex items-center gap-1.5 rounded border border-rule bg-surface px-2.5 py-1.5">
          <Search size={13} className="text-faint" aria-hidden="true" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by name"
            aria-label="Filter evaluations by name"
            className="w-40 bg-transparent text-[12px] outline-none placeholder:text-faint"
          />
        </label>
      </div>

      {visible.length === 0 ? (
        <p className="rounded-card border border-rule bg-surface px-5 py-8 text-center text-[13px] text-muted">
          No evaluations match this filter.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-card border border-rule bg-surface">
          <table className="w-full min-w-[40rem] border-collapse">
            <thead>
              <tr className="border-b border-rule">
                <SortHeader
                  label="Asset"
                  active={sortKey === "asset"}
                  ascending={ascending}
                  onClick={() => toggleSort("asset")}
                />
                <SortHeader
                  label="Score"
                  active={sortKey === "score"}
                  ascending={ascending}
                  onClick={() => toggleSort("score")}
                />
                <SortHeader
                  label="Policy"
                  active={sortKey === "policy"}
                  ascending={ascending}
                  onClick={() => toggleSort("policy")}
                />
                <SortHeader
                  label="Date"
                  active={sortKey === "date"}
                  ascending={ascending}
                  onClick={() => toggleSort("date")}
                />
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => {
                const verdict = decisionFor(row.decision, row.status);
                const Icon = verdict.icon;
                return (
                  <tr
                    key={row.run_id}
                    className={`group border-b border-rule last:border-0 ${TONE_ROW[verdict.tone]}`}
                  >
                    <td className={`border-l-2 px-4 py-3 ${TONE_ACCENT[verdict.tone]}`}>
                      <Link href={`/runs/${row.run_id}`} className="flex items-start gap-2">
                        <Icon
                          size={15}
                          strokeWidth={2}
                          className={`mt-0.5 shrink-0 ${TONE_TEXT[verdict.tone]}${
                            verdict.spin ? " spinner" : ""
                          }`}
                          aria-hidden="true"
                        />
                        <span className="min-w-0">
                          <span className="block text-[13px] font-medium group-hover:underline">
                            {row.asset_name}
                          </span>
                          <span className="tnum mt-0.5 block text-[11px] text-faint">
                            {row.identifier}
                          </span>
                          {/* The verdict is carried by colour, so it also has to be
                              readable as text — colour is never the only signal. */}
                          <span className={`mt-0.5 block text-[11px] ${TONE_TEXT[verdict.tone]}`}>
                            {verdict.label}
                          </span>
                        </span>
                      </Link>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <span className="tnum text-[13px]">
                        {row.composite_score ?? <span className="text-faint">—</span>}
                      </span>
                      {row.samples_min != null && (
                        <span className="tnum mt-0.5 block text-[11px] text-faint">
                          n=
                          {row.samples_min === row.samples_max
                            ? row.samples_min
                            : `${row.samples_min}–${row.samples_max}`}
                        </span>
                      )}
                      {row.sample_override != null && (
                        <span
                          className="mt-0.5 flex items-center gap-1 text-[11px] font-medium text-warn"
                          title="Sample counts were overridden for this run, so it is not a policy-governed result."
                        >
                          <FlaskConical size={10} aria-hidden="true" />
                          override
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 align-top">
                      <span className="tnum text-[12px]">
                        {row.policy_version ? `v${row.policy_version}` : "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3 align-top">
                      <span className="tnum text-[12px] text-muted" suppressHydrationWarning>
                        {new Date(row.started_at + "Z").toLocaleString(undefined, {
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    </td>
                    <td className="px-2 align-top">
                      <Link
                        href={`/runs/${row.run_id}`}
                        aria-label={`Open ${row.asset_name}`}
                        className="block py-3"
                      >
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
      )}

      <p className="text-[11px] text-muted">
        Gates, judge model and per-benchmark detail are on each evaluation&apos;s page. Score
        is a weighted composite shown only when every benchmark was measured; it orders the
        table and never decides an outcome.
      </p>
    </div>
  );
}

function SortHeader({
  label,
  active,
  ascending,
  onClick,
}: {
  label: string;
  active: boolean;
  ascending: boolean;
  onClick: () => void;
}) {
  const Arrow = ascending ? ArrowUp : ArrowDown;
  return (
    <th className="px-4 py-2.5 text-left">
      <button
        onClick={onClick}
        aria-sort={active ? (ascending ? "ascending" : "descending") : "none"}
        className={`eyebrow flex items-center gap-1 transition-colors hover:text-ink ${
          active ? "text-ink" : ""
        }`}
      >
        {label}
        {active && <Arrow size={11} aria-hidden="true" />}
      </button>
    </th>
  );
}
