import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowUpRight, Check, FileJson, FlaskConical, X } from "lucide-react";
import { fetchRun, type Run } from "@/lib/api";
import { Term } from "../../ui/term";
import { ThresholdRule } from "../../ui/threshold-rule";
import {
  PROVENANCE_ICON,
  SEVERITY,
  SEVERITY_ORDER,
  TONE_PANEL,
  TONE_TEXT,
  decisionFor,
} from "../../ui/vocabulary";
import { LiveProgress } from "./live-progress";

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = await fetchRun(id);
  if (!run) notFound();

  return (
    <div className="space-y-10">
      <section className="space-y-3">
        <Link
          href="/evaluations"
          className="inline-flex items-center gap-1.5 text-[12px] text-muted transition-colors hover:text-ink"
        >
          <ArrowLeft size={13} aria-hidden="true" />
          Results
        </Link>
        <div>
          <h1 className="text-[26px] font-semibold leading-tight tracking-tight">
            {run.asset_name}
          </h1>
          <p className="tnum mt-1 text-[12px] text-faint">{run.identifier}</p>
        </div>
      </section>

      <Verdict run={run} />
      {run.asset_type === "llm" && run.gate_outcomes.length > 0 && <Gates run={run} />}
      {run.findings.length > 0 && <Findings run={run} />}
      <Provenance run={run} />
      <ExtraMetrics run={run} />
      {run.artifacts.length > 0 && <Artifacts run={run} />}
      {run.error && (
        <section className="space-y-2">
          <h2 className="eyebrow">Errors</h2>
          <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded-card border border-block/30 bg-block-wash p-3 text-[11px] leading-relaxed text-block">
            {run.error}
          </pre>
        </section>
      )}
    </div>
  );
}

function Verdict({ run }: { run: Run }) {
  const verdict = decisionFor(run.decision, run.status);
  const Icon = verdict.icon;
  const running = run.status === "running" || run.status === "pending";

  return (
    <section className={`rounded-card border p-5 ${TONE_PANEL[verdict.tone]}`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-wrap items-center gap-2.5">
          <Icon
            size={20}
            strokeWidth={2}
            className={`${TONE_TEXT[verdict.tone]}${verdict.spin ? " spinner" : ""}`}
            aria-hidden="true"
          />
          <h2 className={`text-[17px] font-semibold tracking-tight ${TONE_TEXT[verdict.tone]}`}>
            {verdict.label}
          </h2>
          {run.sample_override != null && (
            <span className="flex items-center gap-1 rounded border border-warn/40 bg-warn-wash px-2 py-0.5 text-[11px] font-medium text-warn">
              <FlaskConical size={11} aria-hidden="true" />
              override n={run.sample_override} — not a policy-governed sample size
            </span>
          )}
        </div>
        {run.composite_score != null && (
          <div className="text-right">
            <div className="tnum text-[22px] font-medium leading-none">
              {run.composite_score}
            </div>
            <div className="eyebrow mt-1">display only</div>
          </div>
        )}
      </div>

      <p className="mt-3 max-w-3xl text-[13px] leading-relaxed text-ink/80">
        {running ? "Benchmarks run sequentially against the gateway." : run.decision_reason}
      </p>
      <LiveProgress runId={run.id} status={run.status} />
    </section>
  );
}

function Gates({ run }: { run: Run }) {
  const byCheck = new Map(run.scores.filter((s) => s.gated).map((s) => [s.check_id, s]));

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-[15px] font-semibold tracking-tight">Benchmark gates</h2>
        <p className="mt-1 text-[12px] text-muted">
          One gate per benchmark, compared against the raw metric. These decide the outcome.
        </p>
      </div>

      <div className="overflow-x-auto rounded-card border border-rule bg-surface">
        <table className="w-full min-w-[48rem] border-collapse">
          <thead>
            <tr className="border-b border-rule">
              <th className="eyebrow px-5 py-2.5 text-left font-medium">Benchmark</th>
              <th className="eyebrow px-5 py-2.5 text-left font-medium">Measured</th>
              <th className="eyebrow px-5 py-2.5 text-left font-medium">Against threshold</th>
              <th className="eyebrow px-5 py-2.5 text-left font-medium">Source</th>
              <th className="eyebrow px-5 py-2.5 text-right font-medium">Gate</th>
            </tr>
          </thead>
          <tbody>
            {run.gate_outcomes.map((gate) => {
              const score = byCheck.get(gate.check_id);
              const ProvIcon = score ? PROVENANCE_ICON[score.provenance] : null;
              return (
                <tr key={gate.check_id} className="border-b border-rule last:border-0">
                  <td className="px-5 py-4 align-top">
                    <Link
                      href={`/benchmarks/${gate.check_id}`}
                      className="tnum text-[12px] font-medium hover:underline"
                    >
                      {gate.check_id}
                    </Link>
                    {gate.description && (
                      <div className="mt-1 max-w-xs text-[11px] leading-relaxed text-muted">
                        {gate.description}
                      </div>
                    )}
                  </td>
                  <td className="px-5 py-4 align-top">
                    <div className="tnum text-[15px]">
                      {gate.raw_value == null ? (
                        <span className="text-[12px] text-block">no score</span>
                      ) : (
                        gate.raw_value.toPrecision(3)
                      )}
                    </div>
                    <div className="eyebrow mt-0.5">{gate.metric}</div>
                    {gate.raw_value == null && gate.reason && (
                      <div className="mt-1 max-w-[12rem] text-[11px] leading-relaxed text-muted">
                        {gate.reason}
                      </div>
                    )}
                    {score?.total_samples != null && (
                      <div className="tnum mt-1 text-[11px] text-muted">
                        n={score.total_samples}
                        {score.total_samples < 20 && (
                          <span className="text-warn"> — coarse</span>
                        )}
                      </div>
                    )}
                    {score?.unresolved_samples ? (
                      <div className="tnum mt-1 text-[11px] text-warn">
                        {score.unresolved_samples} unresolved
                      </div>
                    ) : null}
                  </td>
                  <td className="px-5 py-4 align-top">
                    <ThresholdRule
                      value={gate.raw_value}
                      threshold={gate.threshold}
                      direction={gate.direction}
                      passed={gate.passed}
                    />
                  </td>
                  <td className="px-5 py-4 align-top">
                    {score && (
                      <span className="flex items-center gap-1 text-[11px] text-muted">
                        {ProvIcon && <ProvIcon size={12} aria-hidden="true" />}
                        {score.provenance.replace("_", " ")}
                      </span>
                    )}
                    {score?.source_url && (
                      <a
                        href={score.source_url}
                        className="mt-0.5 block text-[11px] text-ink underline"
                      >
                        source
                      </a>
                    )}
                  </td>
                  <td className="px-5 py-4 text-right align-top">
                    <span
                      className={`inline-flex items-center gap-1 text-[12px] font-medium ${
                        gate.passed ? "text-pass" : "text-block"
                      }`}
                    >
                      {gate.passed ? (
                        <Check size={14} strokeWidth={2.5} aria-hidden="true" />
                      ) : (
                        <X size={14} strokeWidth={2.5} aria-hidden="true" />
                      )}
                      {gate.passed ? "Pass" : "Fail"}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function Findings({ run }: { run: Run }) {
  const counts = run.findings.reduce<Record<string, number>>((acc, f) => {
    acc[f.severity] = (acc[f.severity] ?? 0) + 1;
    return acc;
  }, {});
  const sorted = [...run.findings].sort(
    (a, b) => (SEVERITY[a.severity]?.rank ?? 9) - (SEVERITY[b.severity]?.rank ?? 9),
  );

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-semibold tracking-tight">Scanner findings</h2>
          <p className="mt-1 max-w-xl text-[12px] leading-relaxed text-muted">
            The gate is a severity rule over these findings, not a score. Findings keep their
            analyzer attribution so you can slice by engine, but no analyzer subtotal is
            thresholded.
          </p>
        </div>
        <div className="flex gap-3">
          {SEVERITY_ORDER.filter((s) => counts[s]).map((severity) => {
            const Icon = SEVERITY[severity].icon;
            return (
              <span
                key={severity}
                className={`flex items-center gap-1 text-[12px] font-medium ${
                  TONE_TEXT[SEVERITY[severity].tone]
                }`}
              >
                <Icon size={13} aria-hidden="true" />
                <span className="tnum">{counts[severity]}</span>
                <span className="font-normal text-muted">{severity}</span>
              </span>
            );
          })}
        </div>
      </div>

      <div className="overflow-hidden rounded-card border border-rule bg-surface">
        {sorted.map((finding, index) => {
          const meta = SEVERITY[finding.severity] ?? SEVERITY.info;
          const Icon = meta.icon;
          return (
            <article
              key={`${finding.rule_id}-${index}`}
              className="flex gap-3 border-b border-rule p-4 last:border-0"
            >
              <Icon
                size={15}
                className={`mt-0.5 shrink-0 ${TONE_TEXT[meta.tone]}`}
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <h3 className="text-[13px] font-medium">{finding.title}</h3>
                  <span className={`text-[11px] font-medium ${TONE_TEXT[meta.tone]}`}>
                    {finding.severity}
                  </span>
                  <span className="tnum text-[11px] text-faint">{finding.analyzer}</span>
                </div>
                {finding.detail && (
                  <p className="mt-1.5 text-[12px] leading-relaxed text-muted">
                    {finding.detail.slice(0, 400)}
                  </p>
                )}
                <div className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] text-faint">
                  {finding.rule_id && <span className="tnum">{finding.rule_id}</span>}
                  {finding.file_path && <span className="tnum">{finding.file_path}</span>}
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function Provenance({ run }: { run: Run }) {
  const rows: [string, React.ReactNode, React.ReactNode][] = [
    ["subject", <span key="l">Subject model</span>, run.gateway_model ?? "—"],
    [
      "judge",
      <Term
        key="l"
        label="Judge model"
        tip="The model that graded the subject's open-ended answers where a benchmark needs one. A wrong or refusing judge corrupts scores, which is why its reliability is measured."
      />,
      run.judge_model ?? "none required",
    ],
    [
      "unresolved",
      <Term
        key="l"
        label="Judge unresolved (gated)"
        tip="Share of samples where the judge returned no usable verdict — reported by the scorer itself. Above the policy limit, the whole run is voided rather than trusted."
      />,
      run.judge_unresolved_rate == null
        ? "no structural signal"
        : `${(run.judge_unresolved_rate * 100).toFixed(1)}%`,
    ],
    [
      "refusal",
      <Term
        key="l"
        label="Refusal phrasing (advisory)"
        tip="A text heuristic that spots refusal wording in grading explanations. It cannot tell a judge refusal from a subject refusal, so it informs a human and never decides a run."
      />,
      run.judge_refusal_rate == null
        ? "not measured"
        : `${(run.judge_refusal_rate * 100).toFixed(1)}%`,
    ],
    [
      "policy",
      <Term
        key="l"
        label="Policy"
        tip="The exact immutable policy version (and content hash) that governed this run. Later edits create new versions and never change what this run meant."
      />,
      // Linked, because "which policy judged this" is the question a reviewer follows —
      // and it must resolve to the exact version, not whatever is active today.
      run.policy_version ? (
        <Link
          href={`/policies/${run.asset_type}?v=${run.policy_version}`}
          className="inline-flex items-center gap-1 hover:underline"
        >
          v{run.policy_version} · {run.policy_hash}
          <ArrowUpRight size={11} className="text-faint" aria-hidden="true" />
        </Link>
      ) : (
        "—"
      ),
    ],
    ["engine", <span key="l">Scanner engine</span>, run.engine_version ?? "n/a"],
    ["ruleset", <span key="l">Ruleset</span>, run.ruleset_version ?? "n/a"],
  ];

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-[15px] font-semibold tracking-tight">Run provenance</h2>
        <p className="mt-1 text-[12px] text-muted">
          Recorded so this decision stays interpretable later: which models did the work, and
          which policy version produced the verdict — follow it to the exact settings that
          were in force, which no later edit can change.
        </p>
      </div>
      <dl className="grid overflow-hidden rounded-card border border-rule bg-surface sm:grid-cols-2">
        {rows.map(([key, label, value], index) => (
          <div
            key={key}
            className={`flex items-baseline justify-between gap-4 border-rule px-4 py-2.5 ${
              index % 2 === 0 ? "sm:border-r" : ""
            } border-b last:border-b-0 sm:[&:nth-last-child(-n+2)]:border-b-0`}
          >
            <dt className="text-[12px] text-muted">{label}</dt>
            <dd className="tnum text-right text-[12px]">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function ExtraMetrics({ run }: { run: Run }) {
  const extras = run.scores.filter((s) => !s.gated);
  if (extras.length === 0) return null;

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-[15px] font-semibold tracking-tight">Other reported metrics</h2>
        <p className="mt-1 max-w-xl text-[12px] leading-relaxed text-muted">
          Everything else the benchmarks reported. Recorded for inspection and never
          thresholded — forcing these into gates would invent thresholds the benchmarks do not
          support.
        </p>
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-2 rounded-card border border-rule bg-surface px-4 py-3">
        {extras.map((score) => (
          <div key={score.check_id} className="flex items-baseline gap-1.5">
            <span className="tnum text-[12px]">{score.raw_value?.toPrecision(4)}</span>
            <span className="text-[11px] text-faint">{score.check_id.split("::").pop()}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function Artifacts({ run }: { run: Run }) {
  return (
    <section className="space-y-3">
      <h2 className="text-[15px] font-semibold tracking-tight">Artifacts</h2>
      <ul className="space-y-1.5">
        {run.artifacts.map((path) => (
          <li key={path} className="flex items-center gap-2 text-[11px] text-muted">
            <FileJson size={13} className="shrink-0 text-faint" aria-hidden="true" />
            <span className="tnum break-all">{path}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
