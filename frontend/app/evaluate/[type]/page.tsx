import Link from "next/link";
import { notFound } from "next/navigation";
import {
  fetchChecks,
  fetchGatewayStatus,
  fetchModels,
  fetchPolicy,
  type AssetType,
} from "@/lib/api";
import { ScannerForm } from "./scanner-form";
import { SubmitForm } from "./submit-form";

const TITLES: Record<AssetType, { title: string; blurb: string }> = {
  llm: {
    title: "Evaluate a foundation model",
    blurb:
      "Runs the security benchmark suite through the model gateway and compares each result against its own threshold.",
  },
  mcp: {
    title: "Evaluate an MCP server",
    blurb: "Scans the server's source with the full mcp-scanner analyzer set.",
  },
  skill: {
    title: "Evaluate an agent skill",
    blurb: "Scans the skill with the full skill-scanner analyzer set.",
  },
};

export default async function EvaluatePage({
  params,
}: {
  params: Promise<{ type: string }>;
}) {
  const { type } = await params;
  if (type !== "llm" && type !== "mcp" && type !== "skill") notFound();
  const assetType = type as AssetType;

  const [models, checks, policy, gateway] = await Promise.all([
    fetchModels(),
    fetchChecks(assetType),
    fetchPolicy(),
    fetchGatewayStatus(),
  ]);

  const copy = TITLES[assetType];

  if (assetType !== "llm") {
    const scannerPolicy = policy?.scanner?.[assetType];
    return (
      <div className="space-y-8">
        <section className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{copy.title}</h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted">{copy.blurb}</p>
        </section>

        {!gateway?.ok && (
          <p className="rounded border border-fail/40 bg-fail/10 px-4 py-3 text-sm text-fail">
            The model gateway is unreachable. The scanner&apos;s LLM analyzer runs through it,
            so a scan cannot start.
          </p>
        )}

        <ScannerForm assetType={assetType} analyzerModel={policy?.scanner_model ?? "gemma4"} />

        <section className="space-y-3">
          <h2 className="text-sm font-medium">How this is judged</h2>
          <p className="text-xs leading-relaxed text-muted">
            There is no benchmark that scores a specific MCP server or skill — the published
            MCP benchmarks measure how a <em>client model</em> behaves when given servers, not
            whether a given server is safe. So the scanner is the evaluation, and the gate is a
            severity rule rather than a score: scanner findings have no fixed denominator, so a
            0&ndash;100 threshold over them would be invented precision.
          </p>
          {scannerPolicy && (
            <dl className="grid gap-x-6 gap-y-2 rounded-lg border border-edge bg-surface p-4 text-xs sm:grid-cols-2">
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Mode</dt>
                <dd className="font-mono">{scannerPolicy.mode}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Blocks on</dt>
                <dd className="font-mono">{scannerPolicy.block_on.join(", ")}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted">Trusts scanner verdict</dt>
                <dd className="font-mono">{String(scannerPolicy.trust_scanner_verdict)}</dd>
              </div>
            </dl>
          )}
          {scannerPolicy?.mode === "advisory" && (
            <p className="rounded border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
              Advisory mode: every result goes to human review and nothing is auto-approved,
              because the severity rule has no false-positive baseline yet. Flip{" "}
              <code>mode: gating</code> in policy.yaml once the distribution is understood.
            </p>
          )}
          <Link href="/" className="inline-block text-sm text-accent hover:underline">
            Back to asset classes
          </Link>
        </section>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{copy.title}</h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted">{copy.blurb}</p>
      </section>

      {!gateway?.ok && (
        <p className="rounded border border-fail/40 bg-fail/10 px-4 py-3 text-sm text-fail">
          The model gateway is unreachable, so no run can start. Every evaluation goes through
          it.
        </p>
      )}

      <SubmitForm
        models={models ?? []}
        defaultJudge={policy?.judge.default_model ?? "qwen35"}
        defaultSubject={policy?.default_subject_model ?? "gemma4"}
      />

      <section className="space-y-3">
        <h2 className="text-sm font-medium">What gets measured</h2>
        <p className="text-xs text-muted">
          One gate per benchmark, on that benchmark&apos;s own headline metric. Benchmarks
          report other metrics too; those are recorded for inspection and never thresholded.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-edge text-left text-xs text-muted">
                <th className="py-2 pr-4 font-medium">Benchmark</th>
                <th className="py-2 pr-4 font-medium">Metric</th>
                <th className="py-2 pr-4 font-medium">Threshold</th>
                <th className="py-2 pr-4 font-medium">Judge</th>
              </tr>
            </thead>
            <tbody>
              {(checks ?? []).map((check) => {
                const gate = policy?.llm_gates?.[check.id];
                const arrow = check.direction === "higher_is_better" ? "≥" : "≤";
                return (
                  <tr key={check.id} className="border-b border-edge/50 align-top">
                    <td className="py-2 pr-4 font-mono text-xs">{check.id}</td>
                    <td className="py-2 pr-4 text-xs text-muted">{check.metric}</td>
                    <td className="py-2 pr-4 font-mono text-xs">
                      {gate ? `${arrow} ${gate.threshold}` : "—"}
                    </td>
                    <td className="py-2 pr-4 text-xs text-muted">
                      {check.needs_judge ? "yes" : "no"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {policy && !policy.thresholds_are_calibrated && (
          <p className="rounded border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
            Thresholds are not yet calibrated. {policy.calibration_note}
          </p>
        )}
      </section>
    </div>
  );
}
