import { Pin } from "lucide-react";
import type { AssetType, LlmFormValues, ScannerFormValues } from "@/lib/api";

const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const;

/** What a gate actually measures: a pinned core set supersedes the `samples` setting. */
function effectiveSamples(gate: { samples: number; sample_ids_count: number }): number {
  return gate.sample_ids_count > 0 ? gate.sample_ids_count : gate.samples;
}

/**
 * A policy version's settings, rendered as a record rather than a form or a document.
 *
 * This is what "viewing a policy" means: there is no YAML surface anywhere in the UI. The
 * document remains the stored, hashed, versioned artifact — it is simply not the interface.
 * Shared by the policy page (viewing any version) and the criteria page (what governs runs
 * right now), so the two can never drift into describing the policy differently.
 */
export function PolicySettings({
  assetType,
  values,
}: {
  assetType: AssetType;
  values: LlmFormValues | ScannerFormValues;
}) {
  if (assetType === "llm") {
    const llm = values as LlmFormValues;
    const enabled = Object.entries(llm.gates).filter(([, g]) => g.enabled);
    const available = Object.entries(llm.gates).filter(([, g]) => !g.enabled);
    const totalCalls = enabled.reduce(
      (sum, [, g]) => sum + effectiveSamples(g) * g.calls_per_sample,
      0,
    );

    return (
      <div className="space-y-5">
        <dl className="grid overflow-hidden rounded-card border border-rule bg-surface sm:grid-cols-3">
          {[
            ["Judge model", llm.judge_default_model],
            [
              "Max unresolved verdicts",
              `${(llm.judge_max_refusal_rate * 100).toFixed(1)}%`,
            ],
            ["Estimated cost per run", `~${totalCalls} model calls`],
          ].map(([label, value], index) => (
            <div
              key={label}
              className={`border-b border-rule px-4 py-3 last:border-b-0 sm:border-b-0 ${
                index < 2 ? "sm:border-r" : ""
              }`}
            >
              <dt className="eyebrow">{label}</dt>
              <dd className="tnum mt-1 text-[12px]">{value}</dd>
            </div>
          ))}
        </dl>

        <div className="overflow-x-auto rounded-card border border-rule bg-surface">
          <table className="w-full min-w-[38rem] border-collapse">
            <thead>
              <tr className="border-b border-rule">
                <th className="eyebrow px-4 py-2.5 text-left font-medium">
                  Benchmark suite ({enabled.length})
                </th>
                <th className="eyebrow px-4 py-2.5 text-left font-medium">Passes when</th>
                <th className="eyebrow px-4 py-2.5 text-left font-medium">Samples</th>
                <th className="eyebrow px-4 py-2.5 text-left font-medium">Weight</th>
                <th className="eyebrow px-4 py-2.5 text-left font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {enabled.map(([id, gate]) => (
                <tr key={id} className="border-b border-rule last:border-0">
                  <td className="px-4 py-3">
                    <div className="tnum text-[12px] font-medium">{id}</div>
                    <div className="mt-0.5 max-w-md text-[11px] leading-relaxed text-muted">
                      {gate.description}
                    </div>
                  </td>
                  <td className="tnum px-4 py-3 text-[12px]">
                    {gate.metric} {gate.direction === "higher_is_better" ? "≥" : "≤"}{" "}
                    {gate.threshold}
                  </td>
                  <td className="px-4 py-3">
                    <span className="tnum text-[12px]">{effectiveSamples(gate)}</span>
                    {gate.sample_ids_count > 0 && (
                      <span
                        className="ml-1.5 inline-flex items-center gap-0.5 text-[11px] font-medium text-pass"
                        title="A fixed core set: these exact sample ids run every time, so this count governs rather than the samples setting."
                      >
                        <Pin size={10} aria-hidden="true" />
                        pinned
                      </span>
                    )}
                  </td>
                  <td className="tnum px-4 py-3 text-[12px]">{gate.weight}</td>
                  <td className="tnum px-4 py-3 text-[12px] text-muted">
                    ~{effectiveSamples(gate) * gate.calls_per_sample} calls
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {available.length > 0 && (
          <p className="text-[12px] leading-relaxed text-muted">
            <span className="font-medium text-ink">Available, not in the suite:</span>{" "}
            <span className="tnum">{available.map(([id]) => id).join(", ")}</span>. Add one
            from Edit settings; a benchmark that is not in the suite does not run.
          </p>
        )}

        <dl className="grid overflow-hidden rounded-card border border-rule bg-surface sm:grid-cols-2">
          {[
            [
              "Blocks on an unsafe weight file",
              llm.weights_block_on_unsafe_file ? "yes" : "no",
            ],
            [
              "Treats unscanned repos as passing",
              llm.weights_treat_unscanned_as_pass ? "yes" : "no",
            ],
          ].map(([label, value], index) => (
            <div
              key={label}
              className={`border-b border-rule px-4 py-3 last:border-b-0 sm:border-b-0 ${
                index < 1 ? "sm:border-r" : ""
              }`}
            >
              <dt className="eyebrow">{label}</dt>
              <dd className="mt-1 text-[12px]">{value}</dd>
            </div>
          ))}
        </dl>
      </div>
    );
  }

  const scanner = values as ScannerFormValues;
  return (
    <div className="space-y-5">
      <dl className="grid overflow-hidden rounded-card border border-rule bg-surface sm:grid-cols-4">
        {[
          ["Decision mode", scanner.mode],
          ["Blocks on", scanner.block_on.join(", ")],
          ["Trusts scanner verdict", scanner.trust_scanner_verdict ? "yes" : "no"],
          ["Files examined per scan", String(scanner.max_source_files)],
        ].map(([label, value], index) => (
          <div
            key={label}
            className={`border-b border-rule px-4 py-3 last:border-b-0 sm:border-b-0 ${
              index < 3 ? "sm:border-r" : ""
            }`}
          >
            <dt className="eyebrow">{label}</dt>
            <dd className="tnum mt-1 text-[12px]">{value}</dd>
          </div>
        ))}
      </dl>
      <div className="rounded-card border border-rule bg-surface px-4 py-3">
        <div className="eyebrow mb-2">Severity roll-up (orders results; never gates)</div>
        <div className="flex flex-wrap gap-4">
          {SEVERITIES.map((severity) => (
            <span key={severity} className="text-[12px]">
              <span className="tnum text-muted">{severity}</span>{" "}
              <span className="tnum">{scanner.severity_rollup_penalty[severity] ?? 0}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
