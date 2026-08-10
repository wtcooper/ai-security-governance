import Link from "next/link";
import { ArrowRight, Check, LineChart, ShieldCheck } from "lucide-react";
import { type AssetType } from "@/lib/api";
import { ASSET } from "./ui/vocabulary";

const ORDER: AssetType[] = ["llm", "mcp", "skill"];

/**
 * The platform's promises, stated as properties rather than marketing. They answer the
 * question a submitter actually has before uploading anything: what happens to my asset?
 */
const ASSURANCES: { icon: typeof Check; label: string }[] = [
  { icon: Check, label: "Nothing submitted is executed" },
  { icon: ShieldCheck, label: "Versioned, written policies" },
  { icon: LineChart, label: "Every verdict fully traceable" },
];

const STEPS: { title: string; body: string; gate?: boolean }[] = [
  {
    title: "Submit",
    body: "A gateway model alias, a repository URL, or a zip upload. Nothing submitted is ever executed.",
  },
  {
    title: "Measure",
    body: "Security benchmarks for models; full scanner sweeps for MCP servers and skills. Sample counts come from the policy.",
  },
  {
    title: "Gate",
    body: "Each measurement is compared against the written threshold in the versioned policy that governs the run.",
    gate: true,
  },
  {
    title: "Decide",
    body: "Passes only when every measurement clears its threshold. Anything short requires review — never silently through.",
  },
];

/**
 * The landing page carries exactly one decision: which asset class to evaluate. Gateway
 * state lives in the header pill; policies, benchmarks and results have their own pages.
 */
export default function Home() {
  return (
    <div className="space-y-12">
      <section className="max-w-2xl space-y-3.5">
        <h1 className="text-[28px] font-semibold leading-tight tracking-tight">
          Evaluate an AI asset
        </h1>
        <p className="text-[14px] leading-relaxed text-muted">
          Determines whether an asset clears the security thresholds set in policy, or whether
          it requires review. Every result is measured against a written, versioned policy and
          records which models and which policy produced it.
        </p>
        <ul className="flex flex-wrap gap-2 pt-2">
          {ASSURANCES.map(({ icon: Icon, label }) => (
            <li
              key={label}
              className="flex items-center gap-1.5 rounded-full border border-rule-strong bg-surface px-3 py-1.5 text-[12px] font-medium text-muted"
            >
              <Icon size={13} strokeWidth={2} className="text-accent" aria-hidden="true" />
              {label}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="eyebrow mb-3.5">Choose an asset class</h2>
        <div className="grid gap-4 sm:grid-cols-3">
          {ORDER.map((slug) => {
            const asset = ASSET[slug];
            const Icon = asset.icon;
            return (
              <Link
                key={slug}
                href={`/evaluate/${slug}`}
                className="group flex flex-col gap-3 rounded-card border border-rule bg-surface p-5 shadow-[0_1px_2px_rgb(23_28_35/0.04)] transition-[border-color,box-shadow] hover:border-accent hover:shadow-[0_2px_10px_rgb(43_79_158/0.10)]"
              >
                <span className="grid h-[34px] w-[34px] place-items-center rounded-lg bg-accent-wash text-accent">
                  <Icon size={17} strokeWidth={1.75} aria-hidden="true" />
                </span>
                <div className="space-y-1.5">
                  <h3 className="text-[14px] font-semibold">{asset.label}</h3>
                  <p className="text-[12.5px] leading-relaxed text-muted">{asset.blurb}</p>
                </div>
                <span className="mt-auto flex items-center gap-1 pt-1 text-[13px] font-semibold text-accent">
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
        <h2 className="eyebrow mb-3.5">How it works</h2>
        <ol className="rounded-card border border-rule bg-surface py-1 shadow-[0_1px_2px_rgb(23_28_35/0.04)]">
          {STEPS.map(({ title, body, gate }, index) => (
            <li
              key={title}
              className="relative grid items-baseline gap-x-4 gap-y-1 border-rule px-6 py-4 not-first:border-t sm:grid-cols-[40px_130px_1fr]"
            >
              {/* The rail: every step gets a tick; only the gate — where policy bites — is cobalt. */}
              <span
                aria-hidden="true"
                className={`absolute top-3.5 bottom-3.5 left-0 w-[3px] rounded-r-sm ${
                  gate ? "bg-accent" : "bg-rule-strong"
                }`}
              />
              <span className={`tnum text-[11px] ${gate ? "text-accent" : "text-faint"}`}>
                {String(index + 1).padStart(2, "0")}
              </span>
              <h3 className="text-[13.5px] font-semibold">{title}</h3>
              <p className="text-[13px] leading-relaxed text-muted sm:col-auto col-span-full">
                {body}
              </p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
