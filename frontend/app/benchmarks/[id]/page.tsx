import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Pin } from "lucide-react";
import { fetchBenchmark } from "@/lib/api";
import { Term } from "../../ui/term";
import { PreviewSection } from "./preview-section";

/**
 * One benchmark, explained end to end: intent, gate, dataset, real test cases, and the
 * core-set tooling that makes runs repeatable.
 */
export default async function BenchmarkPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const benchmark = await fetchBenchmark(id);
  if (!benchmark) notFound();

  const arrow = benchmark.direction === "higher_is_better" ? "≥" : "≤";

  return (
    <div className="space-y-10">
      <section className="space-y-3">
        <Link
          href="/benchmarks"
          className="inline-flex items-center gap-1.5 text-[12px] text-muted transition-colors hover:text-ink"
        >
          <ArrowLeft size={13} aria-hidden="true" />
          Benchmarks
        </Link>
        <div>
          <h1 className="tnum text-[26px] font-semibold leading-tight tracking-tight">
            {benchmark.id}
          </h1>
          <p className="mt-1 text-[13px] text-muted">{benchmark.description}</p>
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-[15px] font-semibold tracking-tight">What this measures</h2>
        <p className="max-w-3xl text-[13px] leading-relaxed text-ink/85">{benchmark.intent}</p>
      </section>

      <section className="space-y-3">
        <h2 className="text-[15px] font-semibold tracking-tight">Active gate</h2>
        <dl className="grid overflow-hidden rounded-card border border-rule bg-surface sm:grid-cols-4">
          {[
            [
              "Metric",
              <span key="m" className="tnum">
                {benchmark.metric}
              </span>,
            ],
            [
              "Threshold",
              <span key="t" className="tnum">
                {benchmark.gate ? `${arrow} ${benchmark.gate.threshold}` : "not gated"}
              </span>,
            ],
            [
              "Samples per run",
              benchmark.gate?.uses_core_set ? (
                <span key="s" className="flex items-center gap-1.5">
                  <Pin size={12} className="text-pass" aria-hidden="true" />
                  <span className="tnum">{benchmark.gate.sample_ids_count} pinned</span>
                </span>
              ) : (
                <span key="s" className="tnum">
                  {benchmark.gate?.samples ?? "—"}
                  <span className="text-faint"> (first N of dataset)</span>
                </span>
              ),
            ],
            [
              "Judge model",
              <span key="j">{benchmark.needs_judge ? "required" : "not needed"}</span>,
            ],
          ].map(([label, value], index) => (
            <div
              key={index}
              className={`border-b border-rule px-4 py-3 last:border-b-0 sm:border-b-0 ${
                index < 3 ? "sm:border-r" : ""
              }`}
            >
              <dt className="eyebrow">{label}</dt>
              <dd className="mt-1 text-[12px]">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="max-w-3xl text-[12px] leading-relaxed text-muted">
          {benchmark.gate?.uses_core_set ? (
            <>
              This benchmark runs a{" "}
              <Term
                label="fixed core set"
                tip="An explicit list of dataset sample ids stored in the versioned policy. Every run measures exactly these cases, so results are repeatable across runs and comparable across models."
              />
              : the same test cases every run, pinned in the policy. Changing them is a
              policy edit with a version number attached.
            </>
          ) : (
            <>
              This benchmark currently draws the dataset&apos;s first N samples —
              deterministic, but the head of a dataset is not representative. Propose a{" "}
              <Term
                label="core set"
                tip="A stratified, seeded selection of sample ids. Stratification mirrors the dataset's composition; the seed makes the draw reproducible. Adopting it pins the list in the versioned policy."
              />{" "}
              below and adopt it in the policy to make runs repeatable and representative.
            </>
          )}
        </p>
      </section>

      <PreviewSection benchmark={benchmark} />
    </div>
  );
}
