import Link from "next/link";
import { ArrowRight, FlaskConical, Pin } from "lucide-react";
import { fetchBenchmarks } from "@/lib/api";

/**
 * The benchmark suite, explained. One card per benchmark: what it measures, over how many
 * samples, against what threshold — with the full explanation and real test cases one
 * click deeper.
 */
export default async function BenchmarksPage() {
  const data = await fetchBenchmarks();
  const benchmarks = data?.benchmarks ?? null;
  const suite = data?.suite;

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h1 className="text-[26px] font-semibold leading-tight tracking-tight">Benchmarks</h1>
        <p className="max-w-2xl text-[13.5px] leading-relaxed text-muted">
          The LLM security suite: one gate per benchmark, on that benchmark&apos;s own
          headline metric. Each page explains the intent, shows real test cases from the
          dataset, and manages the fixed core set that makes runs repeatable. Which
          benchmarks are in the suite — and over how many samples — is set by the policy.
        </p>
      </section>

      {suite && (
        <dl className="grid overflow-hidden rounded-card border border-rule bg-surface sm:grid-cols-4">
          {[
            ["In the suite", String(suite.enabled_count)],
            ["Available to add", String(suite.available_count)],
            ["Need a judge model", String(suite.judged_count)],
            ["Cost per run", `~${suite.estimated_calls} model calls`],
          ].map(([label, value], index) => (
            <div
              key={label}
              className={`border-b border-rule px-4 py-3 last:border-b-0 sm:border-b-0 ${
                index < 3 ? "sm:border-r" : ""
              }`}
            >
              <dt className="eyebrow">{label}</dt>
              <dd className="tnum mt-1 text-[13px]">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {benchmarks === null ? (
        <p className="text-[13px] text-block">Could not reach the backend.</p>
      ) : (
        <div className="grid gap-px overflow-hidden rounded-card border border-rule bg-rule">
          {benchmarks.map((benchmark) => (
            <Link
              key={benchmark.id}
              href={`/benchmarks/${benchmark.id}`}
              className="group flex flex-col gap-2 bg-surface p-5 transition-colors hover:bg-paper sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <FlaskConical size={14} className="shrink-0 text-ink" aria-hidden="true" />
                  <h2 className="tnum text-[13px] font-medium">{benchmark.id}</h2>
                  {!benchmark.enabled && (
                    <span className="rounded border border-rule px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted">
                      not in suite
                    </span>
                  )}
                  {benchmark.gate?.uses_core_set && (
                    <span className="flex items-center gap-1 text-[11px] font-medium text-pass">
                      <Pin size={11} aria-hidden="true" />
                      fixed core set
                    </span>
                  )}
                </div>
                <p className="text-[12px] leading-relaxed text-muted">
                  {benchmark.description}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-5 text-[12px]">
                <div className="text-right">
                  <div className="eyebrow">Samples</div>
                  <div className="tnum mt-0.5">
                    {benchmark.gate?.uses_core_set
                      ? `${benchmark.gate.sample_ids_count} pinned`
                      : (benchmark.gate?.samples ?? "—")}
                    {(benchmark.dataset_total ?? benchmark.dataset_size) != null && (
                      <span className="text-faint">
                        {" "}
                        / {benchmark.dataset_total ?? benchmark.dataset_size}
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-right">
                  <div className="eyebrow">Gate</div>
                  <div className="tnum mt-0.5">
                    {benchmark.gate
                      ? `${benchmark.direction === "higher_is_better" ? "≥" : "≤"} ${benchmark.gate.threshold}`
                      : "—"}
                  </div>
                </div>
                <div className="text-right">
                  <div className="eyebrow">Cost</div>
                  <div className="tnum mt-0.5">
                    {benchmark.estimated_calls != null
                      ? `~${benchmark.estimated_calls}`
                      : "—"}
                    <span className="text-faint"> calls</span>
                  </div>
                </div>
                <ArrowRight
                  size={14}
                  className="text-faint transition-transform group-hover:translate-x-0.5"
                  aria-hidden="true"
                />
              </div>
            </Link>
          ))}
        </div>
      )}

      <p className="max-w-2xl text-[12px] leading-relaxed text-muted">
        MCP servers and agent skills are not benchmarked — no published benchmark can score a
        specific submitted artifact. They are evaluated by full scanner sweeps instead; each
        evaluate page explains how its severity rule reads.
      </p>
    </div>
  );
}
