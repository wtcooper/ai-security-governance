import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Info, TriangleAlert } from "lucide-react";
import {
  fetchChecks,
  fetchGatewayStatus,
  fetchModels,
  fetchPolicy,
  type AssetType,
} from "@/lib/api";
import { ASSET } from "../../ui/vocabulary";
import { ScannerForm } from "./scanner-form";
import { SubmitForm } from "./submit-form";

export default async function EvaluatePage({ params }: { params: Promise<{ type: string }> }) {
  const { type } = await params;
  if (type !== "llm" && type !== "mcp" && type !== "skill") notFound();
  const assetType = type as AssetType;

  const [models, checks, policy, gateway] = await Promise.all([
    fetchModels(),
    fetchChecks(assetType),
    fetchPolicy(),
    fetchGatewayStatus(),
  ]);

  const asset = ASSET[assetType];
  const Icon = asset.icon;
  const scanner = policy?.scanner?.[assetType];

  return (
    <div className="space-y-10">
      <section className="space-y-3">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-[12px] text-muted transition-colors hover:text-ink"
        >
          <ArrowLeft size={13} aria-hidden="true" />
          Asset classes
        </Link>
        <div className="flex items-center gap-2.5">
          <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
          <h1 className="text-[26px] font-semibold leading-tight tracking-tight">
            {asset.label}
          </h1>
        </div>
      </section>

      {!gateway?.ok && (
        <p className="flex gap-2 rounded-card border border-block/30 bg-block-wash px-4 py-3 text-[12px] leading-relaxed text-block">
          <TriangleAlert size={14} className="mt-px shrink-0" aria-hidden="true" />
          The model gateway is unreachable, so no run can start. Every evaluation goes through
          it.
        </p>
      )}

      {assetType === "llm" ? (
        <>
          <SubmitForm
            models={models ?? []}
            defaultJudge={policy?.judge.default_model ?? "qwen35"}
            defaultSubject={policy?.default_subject_model ?? "gemma4"}
          />

          <section className="space-y-3">
            <div>
              <h2 className="text-[15px] font-semibold tracking-tight">What gets measured</h2>
              <p className="mt-1 max-w-xl text-[12px] leading-relaxed text-muted">
                One gate per benchmark, on that benchmark&apos;s own headline metric. Benchmarks
                report other metrics too; those are recorded for inspection and never
                thresholded.
              </p>
            </div>

            <div className="overflow-x-auto rounded-card border border-rule bg-surface">
              <table className="w-full min-w-[36rem] border-collapse">
                <thead>
                  <tr className="border-b border-rule">
                    <th className="eyebrow px-5 py-2.5 text-left font-medium">Benchmark</th>
                    <th className="eyebrow px-5 py-2.5 text-left font-medium">Metric</th>
                    <th className="eyebrow px-5 py-2.5 text-left font-medium">Threshold</th>
                    <th className="eyebrow px-5 py-2.5 text-left font-medium">Judge</th>
                  </tr>
                </thead>
                <tbody>
                  {(checks ?? []).map((check) => {
                    const gate = policy?.llm_gates?.[check.id];
                    const arrow = check.direction === "higher_is_better" ? "≥" : "≤";
                    return (
                      <tr key={check.id} className="border-b border-rule last:border-0">
                        <td className="tnum px-5 py-3 text-[12px]">{check.id}</td>
                        <td className="px-5 py-3 text-[12px] text-muted">{check.metric}</td>
                        <td className="tnum px-5 py-3 text-[12px]">
                          {gate ? `${arrow} ${gate.threshold}` : "—"}
                        </td>
                        <td className="px-5 py-3 text-[12px] text-muted">
                          {check.needs_judge ? "yes" : "no"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {policy && !policy.thresholds_are_calibrated && (
              <p className="flex gap-2 rounded-card border border-warn/30 bg-warn-wash px-4 py-3 text-[12px] leading-relaxed text-warn">
                <Info size={14} className="mt-px shrink-0" aria-hidden="true" />
                <span>
                  <strong className="font-medium">Thresholds are not yet calibrated.</strong>{" "}
                  {policy.calibration_note}
                </span>
              </p>
            )}
          </section>
        </>
      ) : (
        <>
          <ScannerForm assetType={assetType} analyzerModel={policy?.scanner_model ?? "gemma4"} />

          <section className="space-y-3">
            <div>
              <h2 className="text-[15px] font-semibold tracking-tight">How this is judged</h2>
              <p className="mt-1 max-w-2xl text-[12px] leading-relaxed text-muted">
                There is no benchmark that scores a specific MCP server or skill — the published
                MCP benchmarks measure how a <em>client model</em> behaves when given servers,
                not whether a given server is safe. So the scanner is the evaluation, and the
                gate is a severity rule rather than a score: scanner findings have no fixed
                denominator, so a 0–100 threshold over them would be invented precision.
              </p>
            </div>

            {scanner && (
              <dl className="grid overflow-hidden rounded-card border border-rule bg-surface sm:grid-cols-3">
                {[
                  ["Mode", scanner.mode],
                  ["Blocks on", scanner.block_on.join(", ")],
                  ["Trusts scanner verdict", String(scanner.trust_scanner_verdict)],
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
            )}

            {scanner?.mode === "advisory" && (
              <p className="flex gap-2 rounded-card border border-warn/30 bg-warn-wash px-4 py-3 text-[12px] leading-relaxed text-warn">
                <Info size={14} className="mt-px shrink-0" aria-hidden="true" />
                <span>
                  <strong className="font-medium">Advisory mode.</strong> Every result goes to
                  human review and nothing is auto-approved, because the severity rule has no
                  false-positive baseline yet. Set <code className="tnum">mode: gating</code> in
                  policy.yaml once the distribution is understood.
                </span>
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
