import Link from "next/link";
import { notFound } from "next/navigation";
import {
  fetchChecks,
  fetchGatewayStatus,
  fetchModels,
  fetchPolicy,
  type AssetType,
} from "@/lib/api";
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
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold tracking-tight">{copy.title}</h1>
        <div className="rounded-lg border border-edge bg-surface p-6">
          <p className="text-sm text-warn">Not implemented yet.</p>
          <p className="mt-2 text-sm text-muted">{copy.blurb}</p>
          <Link href="/" className="mt-4 inline-block text-sm text-accent hover:underline">
            Back to asset classes
          </Link>
        </div>
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
