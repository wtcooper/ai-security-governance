import Link from "next/link";
import { notFound } from "next/navigation";
import { fetchRun, type Run } from "@/lib/api";

const DECISION_STYLE: Record<string, string> = {
  auto_approve: "border-pass/40 bg-pass/10 text-pass",
  needs_deep_testing: "border-warn/40 bg-warn/10 text-warn",
  error: "border-fail/40 bg-fail/10 text-fail",
};

const DECISION_LABEL: Record<string, string> = {
  auto_approve: "Auto-approve",
  needs_deep_testing: "Needs deep testing",
  error: "Error — no decision",
};

const PROVENANCE_STYLE: Record<string, string> = {
  published: "bg-accent/15 text-accent",
  harvested: "bg-accent/15 text-accent",
  self_run: "bg-edge text-muted",
};

export default async function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const run = await fetchRun(id);
  if (!run) notFound();

  const running = run.status === "running" || run.status === "pending";

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <Link href="/leaderboard" className="text-xs text-muted hover:text-white">
          ← Leaderboards
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">{run.asset_name}</h1>
        <p className="font-mono text-xs text-muted">{run.identifier}</p>
      </section>

      <DecisionPanel run={run} running={running} />
      <Provenance run={run} />
      {run.asset_type === "llm" && <Gates run={run} />}
      {run.findings.length > 0 && <Findings run={run} />}
      <ExtraMetrics run={run} />
      {run.artifacts.length > 0 && <Artifacts run={run} />}
      {run.error && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium">Errors</h2>
          <pre className="max-h-60 overflow-auto whitespace-pre-wrap rounded border border-fail/40 bg-fail/10 p-3 text-xs text-fail">
            {run.error}
          </pre>
        </section>
      )}
    </div>
  );
}

function DecisionPanel({ run, running }: { run: Run; running: boolean }) {
  if (running) {
    return (
      <section className="rounded-lg border border-edge bg-surface p-5">
        <p className="text-sm">
          Evaluation in progress — <span className="text-muted">{run.status}</span>
        </p>
        <p className="mt-2 text-xs text-muted">
          Benchmarks run sequentially against the gateway. Reload for an update.
        </p>
      </section>
    );
  }

  const style = run.decision ? DECISION_STYLE[run.decision] : "border-edge bg-surface text-muted";
  return (
    <section className={`space-y-2 rounded-lg border p-5 ${style}`}>
      <div className="flex items-baseline justify-between gap-4">
        <h2 className="text-base font-medium">
          {run.decision ? (DECISION_LABEL[run.decision] ?? run.decision) : "No decision"}
        </h2>
        {run.composite_score != null && (
          <span className="font-mono text-sm">
            {run.composite_score}
            <span className="ml-1 text-xs opacity-70">/100 display only</span>
          </span>
        )}
      </div>
      {run.decision_reason && <p className="text-sm leading-relaxed">{run.decision_reason}</p>}
    </section>
  );
}

function Provenance({ run }: { run: Run }) {
  const rows: [string, string][] = [
    ["Subject model", run.gateway_model ?? "—"],
    ["Judge model", run.judge_model ?? "none required"],
    [
      "Judge refusal rate",
      run.judge_refusal_rate == null
        ? "not measured"
        : `${(run.judge_refusal_rate * 100).toFixed(1)}%`,
    ],
    ["Policy", run.policy_version ? `v${run.policy_version} (${run.policy_hash})` : "—"],
    ["Scanner engine", run.engine_version ?? "n/a"],
    ["Ruleset", run.ruleset_version ?? "n/a"],
  ];
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium">Run provenance</h2>
      <p className="text-xs text-muted">
        Recorded so a decision stays interpretable later: which models did the work, and which
        policy produced the verdict.
      </p>
      <dl className="grid gap-x-6 gap-y-2 rounded-lg border border-edge bg-surface p-4 text-xs sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-4">
            <dt className="text-muted">{label}</dt>
            <dd className="font-mono">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Gates({ run }: { run: Run }) {
  const byCheck = new Map(run.scores.filter((s) => s.gated).map((s) => [s.check_id, s]));

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium">Benchmark gates</h2>
      <p className="text-xs text-muted">
        One gate per benchmark, compared against the raw metric. These decide the outcome.
      </p>
      <div className="overflow-x-auto rounded-lg border border-edge">
        <table className="w-full min-w-[44rem] border-collapse text-sm">
          <thead className="bg-surface">
            <tr className="text-left text-xs text-muted">
              <th className="px-4 py-3 font-medium">Benchmark</th>
              <th className="px-4 py-3 font-medium">Metric</th>
              <th className="px-4 py-3 font-medium">Result</th>
              <th className="px-4 py-3 font-medium">Threshold</th>
              <th className="px-4 py-3 font-medium">Source</th>
              <th className="px-4 py-3 font-medium">Gate</th>
            </tr>
          </thead>
          <tbody>
            {run.gate_outcomes.map((gate) => {
              const score = byCheck.get(gate.check_id);
              const arrow = gate.direction === "higher_is_better" ? "≥" : "≤";
              return (
                <tr key={gate.check_id} className="border-t border-edge align-top">
                  <td className="px-4 py-3">
                    <div className="font-mono text-xs">{gate.check_id}</div>
                    {gate.description && (
                      <div className="mt-1 max-w-sm text-[11px] text-muted">
                        {gate.description}
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">{gate.metric}</td>
                  <td className="px-4 py-3 font-mono text-xs">
                    {gate.raw_value == null ? (
                      <span className="text-fail">no score</span>
                    ) : (
                      gate.raw_value.toPrecision(3)
                    )}
                    {score?.unresolved_samples ? (
                      <div className="text-[11px] text-warn">
                        {score.unresolved_samples} unresolved
                      </div>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">
                    {arrow} {gate.threshold}
                  </td>
                  <td className="px-4 py-3">
                    {score && (
                      <span
                        className={`rounded px-1.5 py-0.5 text-[11px] ${
                          PROVENANCE_STYLE[score.provenance] ?? "bg-edge text-muted"
                        }`}
                      >
                        {score.provenance}
                      </span>
                    )}
                    {score?.source_url && (
                      <a
                        href={score.source_url}
                        className="ml-1 text-[11px] text-accent hover:underline"
                      >
                        source
                      </a>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded px-2 py-0.5 text-xs ${
                        gate.passed ? "bg-pass/15 text-pass" : "bg-fail/15 text-fail"
                      }`}
                    >
                      {gate.passed ? "pass" : "fail"}
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

const SEVERITY_STYLE: Record<string, string> = {
  critical: "bg-fail/20 text-fail",
  high: "bg-fail/15 text-fail",
  medium: "bg-warn/15 text-warn",
  low: "bg-edge text-muted",
  info: "bg-edge text-muted",
};

const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"];

function Findings({ run }: { run: Run }) {
  const counts = run.findings.reduce<Record<string, number>>((acc, finding) => {
    acc[finding.severity] = (acc[finding.severity] ?? 0) + 1;
    return acc;
  }, {});

  const sorted = [...run.findings].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
  );

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium">Scanner findings</h2>
        <div className="flex flex-wrap gap-1.5">
          {SEVERITY_ORDER.filter((s) => counts[s]).map((severity) => (
            <span
              key={severity}
              className={`rounded px-2 py-0.5 text-[11px] ${SEVERITY_STYLE[severity]}`}
            >
              {counts[severity]} {severity}
            </span>
          ))}
        </div>
      </div>
      <p className="text-xs text-muted">
        The gate is a severity rule over these findings, not a score. Findings keep their
        analyzer attribution so you can slice by engine, but no analyzer subtotal is
        thresholded.
      </p>
      <div className="overflow-x-auto rounded-lg border border-edge">
        <table className="w-full min-w-[46rem] border-collapse text-sm">
          <thead className="bg-surface">
            <tr className="text-left text-xs text-muted">
              <th className="px-4 py-3 font-medium">Severity</th>
              <th className="px-4 py-3 font-medium">Analyzer</th>
              <th className="px-4 py-3 font-medium">Finding</th>
              <th className="px-4 py-3 font-medium">Location</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((finding, index) => (
              <tr key={`${finding.rule_id}-${index}`} className="border-t border-edge align-top">
                <td className="px-4 py-3">
                  <span
                    className={`rounded px-2 py-0.5 text-[11px] ${
                      SEVERITY_STYLE[finding.severity] ?? "bg-edge text-muted"
                    }`}
                  >
                    {finding.severity}
                  </span>
                </td>
                <td className="px-4 py-3 font-mono text-[11px] text-muted">{finding.analyzer}</td>
                <td className="px-4 py-3">
                  <div className="text-xs">{finding.title}</div>
                  {finding.detail && (
                    <div className="mt-1 max-w-2xl text-[11px] leading-relaxed text-muted">
                      {finding.detail.slice(0, 400)}
                    </div>
                  )}
                  {finding.rule_id && (
                    <div className="mt-1 font-mono text-[10px] text-muted">{finding.rule_id}</div>
                  )}
                </td>
                <td className="px-4 py-3 font-mono text-[11px] text-muted">
                  {finding.file_path ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ExtraMetrics({ run }: { run: Run }) {
  const extras = run.scores.filter((s) => !s.gated);
  if (extras.length === 0) return null;
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium">Other reported metrics</h2>
      <p className="text-xs text-muted">
        Everything else the benchmarks reported. Recorded for inspection and never thresholded —
        forcing these into gates would invent thresholds the benchmarks do not support.
      </p>
      <div className="flex flex-wrap gap-2">
        {extras.map((score) => (
          <span
            key={score.check_id}
            className="rounded border border-edge bg-surface px-2 py-1 font-mono text-[11px] text-muted"
          >
            {score.check_id.split("::").pop()}: {score.raw_value?.toPrecision(4)}
          </span>
        ))}
      </div>
    </section>
  );
}

function Artifacts({ run }: { run: Run }) {
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium">Artifacts</h2>
      <ul className="space-y-1">
        {run.artifacts.map((path) => (
          <li key={path} className="font-mono text-[11px] text-muted">
            {path}
          </li>
        ))}
      </ul>
    </section>
  );
}
