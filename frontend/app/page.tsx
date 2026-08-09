import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { type AssetType } from "@/lib/api";
import { ASSET } from "./ui/vocabulary";

const ORDER: AssetType[] = ["llm", "mcp", "skill"];

/**
 * The landing page carries exactly one decision: which asset class to evaluate. Gateway
 * state lives in the header pill; policies, benchmarks and results have their own pages.
 */
export default function Home() {
  return (
    <div className="space-y-12">
      <section className="max-w-2xl space-y-3">
        <h1 className="text-[26px] font-semibold leading-tight tracking-tight">
          Evaluate an AI asset
        </h1>
        <p className="text-[13.5px] leading-relaxed text-muted">
          Determines whether an asset clears our security thresholds and can be auto-approved,
          or whether it needs formal deep testing. Every result is measured against a written,
          versioned policy and records which models and which policy produced it.
        </p>
      </section>

      <section>
        <h2 className="eyebrow mb-3">Choose an asset class</h2>
        <div className="grid gap-px overflow-hidden rounded-card border border-rule bg-rule sm:grid-cols-3">
          {ORDER.map((slug) => {
            const asset = ASSET[slug];
            const Icon = asset.icon;
            return (
              <Link
                key={slug}
                href={`/evaluate/${slug}`}
                className="group flex flex-col gap-3 bg-surface p-5 transition-colors hover:bg-paper"
              >
                <Icon size={18} strokeWidth={1.75} className="text-ink" aria-hidden="true" />
                <div className="space-y-1.5">
                  <h3 className="text-[14px] font-medium">{asset.label}</h3>
                  <p className="text-[12px] leading-relaxed text-muted">{asset.blurb}</p>
                </div>
                <span className="mt-auto flex items-center gap-1 text-[12px] font-medium text-ink">
                  Evaluate
                  <ArrowRight
                    size={13}
                    className="transition-transform group-hover:translate-x-0.5"
                    aria-hidden="true"
                  />
                </span>
              </Link>
            );
          })}
        </div>
      </section>

      <section>
        <h2 className="eyebrow mb-3">How it works</h2>
        <ol className="grid gap-px overflow-hidden rounded-card border border-rule bg-rule sm:grid-cols-4">
          {[
            [
              "Submit",
              "A gateway model alias, a repository URL, or a zip upload. Nothing submitted is ever executed.",
            ],
            [
              "Measure",
              "Security benchmarks for models; full scanner sweeps for MCP servers and skills. Sample counts come from the policy.",
            ],
            [
              "Gate",
              "Each measurement is compared against the written threshold in the versioned policy that governs the run.",
            ],
            [
              "Decide",
              "Auto-approve only when every gate passes. Anything less goes to human deep testing — never silently through.",
            ],
          ].map(([title, body], index) => (
            <li key={title} className="space-y-1.5 bg-surface p-5">
              <div className="flex items-baseline gap-2">
                <span className="tnum text-[11px] text-faint">{index + 1}</span>
                <h3 className="text-[13px] font-medium">{title}</h3>
              </div>
              <p className="text-[12px] leading-relaxed text-muted">{body}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
