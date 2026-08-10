"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Copy, Database, ListChecks, Loader2 } from "lucide-react";
import {
  buildBenchmarkPreview,
  proposeCoreSet,
  type BenchmarkDetail,
  type CoreSetProposal,
} from "@/lib/api";

/**
 * Dataset preview + core-set proposal.
 *
 * The preview (size, strata, real example test cases) is built once by the backend and
 * cached; first build can take minutes because the dataset may download. The proposal is
 * instant once the preview exists, and adopting it is deliberately a copy-into-the-policy
 * step — selection never silently changes what runs.
 */
export function PreviewSection({ benchmark }: { benchmark: BenchmarkDetail }) {
  const router = useRouter();
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onBuild() {
    setBuilding(true);
    setError(null);
    const result = await buildBenchmarkPreview(benchmark.id);
    if (!result.ok) setError(result.error);
    setBuilding(false);
    router.refresh();
  }

  const preview = benchmark.preview;

  return (
    <>
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
              <Database size={15} aria-hidden="true" />
              Dataset
            </h2>
            {preview && (
              // suppressHydrationWarning: toLocaleString legitimately differs between the
              // server's locale and the browser's, and the browser's is the one we want.
              <p className="tnum mt-0.5 text-[11px] text-faint" suppressHydrationWarning>
                {preview.total_samples} test cases · preview built{" "}
                {new Date(preview.built_at).toLocaleString()}
              </p>
            )}
          </div>
          <button
            onClick={onBuild}
            disabled={building}
            className="inline-flex items-center gap-2 rounded border border-rule px-3 py-1.5 text-[12px] font-medium transition-colors hover:border-ink disabled:opacity-40"
          >
            {building && <Loader2 size={12} className="spinner-fast" aria-hidden="true" />}
            {building
              ? "Loading dataset (may download)…"
              : preview
                ? "Rebuild preview"
                : "Build preview"}
          </button>
        </div>

        {error && (
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded border border-block/30 bg-block-wash px-3 py-2 text-[11px] leading-relaxed text-block">
            {error}
          </pre>
        )}

        {!preview && !error && (
          <p className="rounded-card border border-rule bg-surface px-4 py-6 text-center text-[12px] text-muted">
            No preview yet. Building it loads the dataset once (downloads on first use) and
            caches its size, composition and example test cases.
          </p>
        )}

        {preview && (
          <>
            {Object.keys(preview.strata).length > 0 && (
              <div className="rounded-card border border-rule bg-surface px-4 py-3">
                <div className="eyebrow mb-2">
                  Composition by {preview.strata_key ?? "stratum"}
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                  {Object.entries(preview.strata).map(([stratum, count]) => (
                    <span key={stratum} className="text-[12px]">
                      <span className="tnum">{stratum}</span>{" "}
                      <span className="tnum text-faint">{count}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-2">
              <h3 className="eyebrow">Example test cases (verbatim from the dataset)</h3>
              <div className="overflow-hidden rounded-card border border-rule bg-surface">
                {preview.examples.map((example) => (
                  <article
                    key={example.id}
                    className="space-y-1.5 border-b border-rule p-4 last:border-0"
                  >
                    <div className="tnum text-[11px] text-faint">{example.id}</div>
                    <p className="whitespace-pre-wrap text-[12px] leading-relaxed">
                      {example.input}
                    </p>
                    {Object.keys(example.metadata).length > 0 && (
                      <div className="flex flex-wrap gap-x-3 gap-y-1 pt-1">
                        {Object.entries(example.metadata).map(([key, value]) => (
                          <span key={key} className="text-[11px] text-muted">
                            <span className="text-faint">{key}:</span>{" "}
                            <span className="tnum">{value}</span>
                          </span>
                        ))}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            </div>
          </>
        )}
      </section>

      {preview && <CoreSetSection benchmark={benchmark} />}
    </>
  );
}

function CoreSetSection({ benchmark }: { benchmark: BenchmarkDetail }) {
  const [size, setSize] = useState("50");
  const [seed, setSeed] = useState("governance-v1");
  const [proposal, setProposal] = useState<CoreSetProposal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [copied, setCopied] = useState(false);

  async function onPropose() {
    setWorking(true);
    setError(null);
    setProposal(null);
    const result = await proposeCoreSet(benchmark.id, Number(size), seed);
    if (result.ok) setProposal(result.data);
    else setError(result.error);
    setWorking(false);
  }

  async function onCopy() {
    if (!proposal) return;
    await navigator.clipboard.writeText(proposal.yaml_snippet);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <section className="space-y-3">
      <div>
        <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
          <ListChecks size={15} aria-hidden="true" />
          Propose a core set
        </h2>
        <p className="mt-1 max-w-3xl text-[12px] leading-relaxed text-muted">
          A stratified, seeded draw: allocation mirrors the dataset&apos;s composition, and
          the same seed and size reproduce the same ids anywhere. Adopting the proposal is a
          policy edit — paste the snippet over the gate&apos;s <code>samples:</code> line in
          the LLM policy and save it as a new version.
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="space-y-1.5">
          <span className="eyebrow block">Size</span>
          <input
            value={size}
            onChange={(e) => setSize(e.target.value.replace(/\D/g, ""))}
            className="tnum w-24 rounded border border-rule bg-surface px-2.5 py-2 text-[13px]"
          />
        </label>
        <label className="space-y-1.5">
          <span className="eyebrow block">Seed (recorded in the policy)</span>
          <input
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            className="tnum w-52 rounded border border-rule bg-surface px-2.5 py-2 text-[13px]"
          />
        </label>
        <button
          onClick={onPropose}
          disabled={working || !size}
          className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {working ? "Selecting…" : "Propose"}
        </button>
      </div>

      {error && (
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded border border-block/30 bg-block-wash px-3 py-2 text-[11px] leading-relaxed text-block">
          {error}
        </pre>
      )}

      {proposal && (
        <div className="space-y-3 rounded-card border border-rule bg-surface p-4">
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {Object.entries(proposal.allocation).map(([stratum, alloc]) => (
              <span key={stratum} className="text-[12px]">
                <span className="tnum">{stratum}</span>{" "}
                <span className="tnum text-faint">
                  {alloc.selected}/{alloc.available}
                </span>
              </span>
            ))}
          </div>
          <div className="relative">
            <pre className="tnum max-h-64 overflow-auto rounded border border-rule bg-paper p-3 pr-20 text-[11px] leading-relaxed">
              {proposal.yaml_snippet}
            </pre>
            <button
              onClick={onCopy}
              className="absolute right-2 top-2 inline-flex items-center gap-1 rounded border border-rule bg-surface px-2 py-1 text-[11px] font-medium transition-colors hover:border-ink"
            >
              <Copy size={11} aria-hidden="true" />
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="text-[12px] text-muted">
            Same seed + size ⇒ the same ids, every time. Adopt via{" "}
            <a href="/policies/llm" className="font-medium text-ink underline">
              the LLM policy editor
            </a>
            .
          </p>
        </div>
      )}
    </section>
  );
}
