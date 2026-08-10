import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  FlaskConical,
  Gauge,
  Pin,
  ScanSearch,
  ScrollText,
} from "lucide-react";
import {
  fetchBenchmarks,
  fetchPolicy,
  fetchPolicyForm,
  fetchPolicyVersions,
  type AssetType,
  type LlmFormValues,
} from "@/lib/api";
import { PolicySettings } from "../../ui/policy-settings";
import { ASSET, DECISION, PENDING, TONE_TEXT } from "../../ui/vocabulary";

/**
 * How a decision gets made, for one asset class.
 *
 * This page exists because the answer used to live in a collapsed accordion on the results
 * table: what runs, what each measurement has to clear, and what the verdicts mean. Those
 * are the questions a reviewer asks before trusting any row in that table, so they get a
 * page with room to answer them rather than a disclosure triangle.
 */
export default async function CriteriaPage({ params }: { params: Promise<{ type: string }> }) {
  const { type } = await params;
  if (type !== "llm" && type !== "mcp" && type !== "skill") notFound();
  const assetType = type as AssetType;

  const [policy, versions, form, benchmarkData] = await Promise.all([
    fetchPolicy(),
    fetchPolicyVersions(assetType),
    fetchPolicyForm(assetType),
    assetType === "llm" ? fetchBenchmarks() : Promise.resolve(null),
  ]);

  const active = versions?.find((v) => v.is_active);
  const scanner = policy?.scanner?.[assetType];
  const asset = ASSET[assetType];

  return (
    <div className="space-y-10">
      <section className="space-y-3">
        <Link
          href={`/evaluations?type=${assetType}`}
          className="inline-flex items-center gap-1.5 text-[12px] text-muted transition-colors hover:text-ink"
        >
          <ArrowLeft size={13} aria-hidden="true" />
          {asset.label} evaluations
        </Link>
        <div>
          <h1 className="text-[26px] font-semibold leading-tight tracking-tight">
            How {asset.label} evaluations are decided
          </h1>
          <p className="mt-1.5 max-w-3xl text-[13.5px] leading-relaxed text-muted">
            {assetType === "llm"
              ? "Each benchmark produces one measurement, compared against one written threshold. Every threshold has to be satisfied for the asset to pass; anything short requires review. Human judgement is spent setting those thresholds, not on a second decision applied afterwards."
              : "There is no benchmark that scores a specific submitted artifact, so the scanner is the evaluation and the gate is a severity rule rather than a score. Scanner findings have no fixed denominator, which is why a 0–100 threshold over them would be invented precision."}
          </p>
        </div>
      </section>

      <Steps assetType={assetType} />
      <Verdicts assetType={assetType} />

      {assetType === "llm" ? (
        <BenchmarkSuite data={benchmarkData} />
      ) : (
        <SeverityRule scanner={scanner} />
      )}

      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
              <ScrollText size={15} aria-hidden="true" />
              Governing policy
            </h2>
            <p className="mt-1 text-[12px] text-muted">
              Version{" "}
              <span className="tnum">
                v{active?.version ?? "?"} · {active?.content_hash ?? ""}
              </span>{" "}
              — recorded on every run it governs, so editing a threshold never rewrites what a
              past decision meant.
            </p>
          </div>
          <Link
            href={`/policies/${assetType}`}
            className="group flex items-center gap-1 text-[12px] font-medium text-ink hover:underline"
          >
            Edit settings &amp; version history
            <ArrowRight
              size={12}
              className="transition-transform group-hover:translate-x-0.5"
              aria-hidden="true"
            />
          </Link>
        </div>
        {form === null ? (
          <p className="rounded-card border border-rule bg-surface px-4 py-6 text-center text-[12px] text-muted">
            Could not read the governing policy.
          </p>
        ) : assetType === "llm" ? (
          // Only the settings the suite table above does not already state. Rendering the
          // full policy view here would print the same benchmark table twice on one page.
          <JudgeAndSupplyChain values={form.values as LlmFormValues} />
        ) : (
          <PolicySettings assetType={assetType} values={form.values} />
        )}
      </section>
    </div>
  );
}

/** The pipeline, stated once. Four steps, because there are exactly four. */
function Steps({ assetType }: { assetType: AssetType }) {
  const steps: [string, string][] =
    assetType === "llm"
      ? [
          [
            "Submit",
            "A gateway model alias, plus a Hugging Face repo for open weights. Preflighted with a real completion first, so a broken model route fails immediately.",
          ],
          [
            "Measure",
            "Each benchmark in the suite runs over the sample count the policy sets. Published results are reused where they exist; everything else is measured here, and every score records which.",
          ],
          [
            "Gate",
            "Each measurement is compared against its threshold, raw value against raw value. A benchmark that produced no score counts as a failed gate, never a skipped one.",
          ],
          [
            "Decide",
            "Passes only when every measurement clears its threshold and the judge graded reliably. Anything else requires review.",
          ],
        ]
      : [
          [
            "Submit",
            "A repository URL, or a zip upload for code behind an enterprise boundary. Acquired read-only — nothing submitted is ever executed.",
          ],
          [
            "Scan",
            "The scanner's full analyzer set sweeps the source. Every finding is stored with its analyzer, severity, rule and file, so results can be sliced later.",
          ],
          [
            "Gate",
            "A severity rule over the findings, plus the scanner's own verdict where it has one. No analyzer subtotal is ever thresholded.",
          ],
          [
            "Decide",
            "A finding at a blocking severity means the submission requires review. A scan that failed is an error, never a pass.",
          ],
        ];

  return (
    <section>
      <h2 className="eyebrow mb-3">The process</h2>
      <ol className="grid gap-px overflow-hidden rounded-card border border-rule bg-rule sm:grid-cols-4">
        {steps.map(([title, body], index) => (
          <li key={title} className="space-y-1.5 bg-surface p-4">
            <div className="flex items-baseline gap-2">
              <span className="tnum text-[11px] text-faint">{index + 1}</span>
              <h3 className="text-[13px] font-medium">{title}</h3>
            </div>
            <p className="text-[12px] leading-relaxed text-muted">{body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** What each verdict means. The same vocabulary the results table colours rows by. */
function Verdicts({ assetType }: { assetType: AssetType }) {
  const entries: { key: string; text: string }[] =
    assetType === "llm"
      ? [
          {
            key: "pass",
            text: "Every measurement cleared the threshold its policy sets, and the judge graded reliably. All benchmarks in the suite must actually have been measured.",
          },
          {
            key: "requires_review",
            text: "One or more measurements fell short of its threshold, or was never taken. The asset is not rejected — it goes to a human instead of through.",
          },
          {
            key: "error",
            text: "The run errored, or the judge refused or failed to grade too many samples for its scores to be trusted. Scores are kept for inspection but no decision is emitted from them.",
          },
          { key: "running", text: "Benchmarks are still executing against the gateway." },
        ]
      : [
          {
            key: "pass",
            text: "The scan completed with no findings at a blocking severity, and the scanner reported the artifact safe.",
          },
          {
            key: "requires_review",
            text: "A finding at one of the severities the policy blocks on, or a scanner verdict of not safe.",
          },
          {
            key: "error",
            text: "The scanner produced no usable verdict, so there is nothing to decide from.",
          },
          { key: "running", text: "The scanner is still analysing the submission." },
        ];

  return (
    <section className="space-y-3">
      <div>
        <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
          <Gauge size={15} aria-hidden="true" />
          What each verdict means
        </h2>
        <p className="mt-1 text-[12px] text-muted">
          These are the colours the evaluations table uses.
        </p>
      </div>
      <dl className="grid gap-px overflow-hidden rounded-card border border-rule bg-rule sm:grid-cols-2">
        {entries.map(({ key, text }) => {
          const verdict = key === "running" ? PENDING : DECISION[key];
          const Icon = verdict.icon;
          return (
            <div key={key} className="flex gap-2.5 bg-surface p-4">
              <Icon
                size={15}
                strokeWidth={2}
                className={`mt-0.5 shrink-0 ${TONE_TEXT[verdict.tone]}`}
                aria-hidden="true"
              />
              <div>
                <dt className={`text-[13px] font-medium ${TONE_TEXT[verdict.tone]}`}>
                  {verdict.label}
                </dt>
                <dd className="mt-0.5 text-[12px] leading-relaxed text-muted">{text}</dd>
              </div>
            </div>
          );
        })}
      </dl>
    </section>
  );
}

/** The LLM suite: what runs, what it must clear, what it costs. */
function BenchmarkSuite({
  data,
}: {
  data: Awaited<ReturnType<typeof fetchBenchmarks>>;
}) {
  const enabled = (data?.benchmarks ?? []).filter((b) => b.enabled);
  const available = (data?.benchmarks ?? []).filter((b) => !b.enabled);

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
            <FlaskConical size={15} aria-hidden="true" />
            The benchmark suite
          </h2>
          <p className="mt-1 max-w-2xl text-[12px] leading-relaxed text-muted">
            One gate per benchmark, on that benchmark&apos;s own headline metric. Benchmarks
            report other metrics too — those are recorded for inspection and never thresholded.
            {data?.suite && (
              <>
                {" "}
                One full run costs about{" "}
                <span className="tnum">{data.suite.estimated_calls}</span> model calls.
              </>
            )}
          </p>
        </div>
        <Link
          href="/benchmarks"
          className="group flex items-center gap-1 text-[12px] font-medium text-ink hover:underline"
        >
          Benchmark details &amp; test cases
          <ArrowRight
            size={12}
            className="transition-transform group-hover:translate-x-0.5"
            aria-hidden="true"
          />
        </Link>
      </div>

      <div className="overflow-x-auto rounded-card border border-rule bg-surface">
        <table className="w-full min-w-[44rem] border-collapse">
          <thead>
            <tr className="border-b border-rule">
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Benchmark</th>
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Passes when</th>
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Samples</th>
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {enabled.map((benchmark) => (
              <tr key={benchmark.id} className="border-b border-rule align-top last:border-0">
                <td className="px-4 py-3">
                  <Link
                    href={`/benchmarks/${benchmark.id}`}
                    className="tnum text-[12px] font-medium hover:underline"
                  >
                    {benchmark.id}
                  </Link>
                  <div className="mt-0.5 max-w-sm text-[11px] leading-relaxed text-muted">
                    {benchmark.description}
                  </div>
                </td>
                <td className="tnum px-4 py-3 text-[12px]">
                  {benchmark.metric} {benchmark.direction === "higher_is_better" ? "≥" : "≤"}{" "}
                  {benchmark.gate?.threshold}
                </td>
                <td className="px-4 py-3">
                  <span className="tnum text-[12px]">
                    {benchmark.gate?.uses_core_set
                      ? benchmark.gate.sample_ids_count
                      : benchmark.gate?.samples}
                  </span>
                  {benchmark.gate?.uses_core_set && (
                    <span
                      className="ml-1.5 inline-flex items-center gap-0.5 text-[11px] font-medium text-pass"
                      title="A fixed core set: the policy pins exact sample ids, so every run measures the same cases."
                    >
                      <Pin size={10} aria-hidden="true" />
                      pinned
                    </span>
                  )}
                </td>
                <td className="tnum px-4 py-3 text-[12px] text-muted">
                  ~{benchmark.estimated_calls} calls
                  {benchmark.needs_judge && (
                    <span className="block text-[11px] text-faint">needs a judge</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {available.length > 0 && (
        <p className="text-[12px] leading-relaxed text-muted">
          <span className="font-medium text-ink">Available, not in the suite:</span>{" "}
          <span className="tnum">{available.map((b) => b.id).join(", ")}</span>. A benchmark
          that is not in the suite does not run; add one from the policy settings.
        </p>
      )}
    </section>
  );
}

/** The scanner severity rule, and why it is a rule rather than a score. */
function SeverityRule({
  scanner,
}: {
  scanner:
    | { block_on: string[]; trust_scanner_verdict: boolean; max_source_files: number }
    | undefined;
}) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
          <ScanSearch size={15} aria-hidden="true" />
          The severity rule
        </h2>
        <p className="mt-1 max-w-3xl text-[12px] leading-relaxed text-muted">
          The published MCP benchmarks measure how a <em>client model</em> behaves when handed
          servers — none can score a server or skill someone submits. So the scanner is the
          evaluation. Findings are gated on severity presence rather than a count, because a
          finding count tracks how much code there is, not how dangerous it is.
        </p>
      </div>
      {scanner && (
        <dl className="grid overflow-hidden rounded-card border border-rule bg-surface sm:grid-cols-3">
          {[
            ["Blocks on", scanner.block_on.join(", ")],
            ["Trusts scanner verdict", String(scanner.trust_scanner_verdict)],
            ["Files examined per scan", String(scanner.max_source_files)],
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
    </section>
  );
}

/** The LLM policy settings that the suite table above does not already state. */
function JudgeAndSupplyChain({ values }: { values: LlmFormValues }) {
  const rows: [string, string][] = [
    ["Judge model", values.judge_default_model],
    [
      "Max unresolved verdicts",
      `${(values.judge_max_refusal_rate * 100).toFixed(1)}% — above this a run is voided, not made lenient`,
    ],
    ["Blocks on an unsafe weight file", values.weights_block_on_unsafe_file ? "yes" : "no"],
    [
      "Treats unscanned repositories as passing",
      values.weights_treat_unscanned_as_pass ? "yes" : "no — unscanned is not safe",
    ],
  ];
  return (
    <dl className="grid overflow-hidden rounded-card border border-rule bg-surface sm:grid-cols-2">
      {rows.map(([label, value], index) => (
        <div
          key={label}
          className={`border-b border-rule px-4 py-3 ${
            index % 2 === 0 ? "sm:border-r" : ""
          } sm:[&:nth-last-child(-n+2)]:border-b-0`}
        >
          <dt className="eyebrow">{label}</dt>
          <dd className="mt-1 text-[12px]">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
