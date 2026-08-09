import Link from "next/link";
import { notFound } from "next/navigation";
import { BadgeCheck, History } from "lucide-react";
import { fetchPolicyForm, fetchPolicyVersions, type AssetType } from "@/lib/api";
import { ASSET } from "../../ui/vocabulary";
import { PolicyEditor } from "./policy-editor";

const TABS: AssetType[] = ["llm", "mcp", "skill"];

/**
 * Policy version history and editing.
 *
 * One page holds the whole model: the version list on the left is the immutable history,
 * the newest entry is what governs, and "editing" is visibly the act of creating the next
 * entry. Older versions render read-only — there is deliberately no way to change one.
 */
export default async function PolicyPage({
  params,
  searchParams,
}: {
  params: Promise<{ type: string }>;
  searchParams: Promise<{ v?: string }>;
}) {
  const { type } = await params;
  const { v } = await searchParams;
  if (type !== "llm" && type !== "mcp" && type !== "skill") notFound();
  const assetType = type as AssetType;

  const versions = await fetchPolicyVersions(assetType);
  if (!versions || versions.length === 0) {
    return <p className="text-[13px] text-block">Could not load policy versions.</p>;
  }

  const requested = v ? Number(v) : versions[0].version;
  const selectedMeta =
    versions.find((entry) => entry.version === requested) ?? versions[0];
  // The form values for the SELECTED version, so a superseded policy is still inspectable —
  // there is no YAML view to fall back on. The document itself is deliberately NOT fetched
  // here: the editor never renders it, and passing it would ship the whole policy text into
  // the client payload for nothing.
  const form = await fetchPolicyForm(assetType, selectedMeta.version);

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h1 className="text-[26px] font-semibold leading-tight tracking-tight">Policies</h1>
        <p className="max-w-2xl text-[13.5px] leading-relaxed text-muted">
          The policy is the document that controls what runs and what passes: benchmarks,
          sample counts, thresholds, severity rules. Versions are immutable — saving an edit
          creates the next version, and the newest version governs every new run.
        </p>
      </section>

      <nav className="flex gap-6 border-b border-rule">
        {TABS.map((slug) => {
          const Icon = ASSET[slug].icon;
          const isActive = slug === assetType;
          return (
            <Link
              key={slug}
              href={`/policies/${slug}`}
              className={`-mb-px flex items-center gap-1.5 border-b-2 pb-2.5 text-[13px] transition-colors ${
                isActive
                  ? "border-ink font-medium text-ink"
                  : "border-transparent text-muted hover:text-ink"
              }`}
            >
              <Icon size={14} strokeWidth={1.75} aria-hidden="true" />
              {ASSET[slug].label}
            </Link>
          );
        })}
      </nav>

      <div className="grid gap-6 lg:grid-cols-[15rem_1fr]">
        <aside className="space-y-1">
          <h2 className="eyebrow mb-2 flex items-center gap-1.5">
            <History size={12} aria-hidden="true" />
            Versions
          </h2>
          {versions.map((entry) => {
            const isSelected = entry.version === selectedMeta.version;
            return (
              <Link
                key={entry.version}
                href={`/policies/${assetType}?v=${entry.version}`}
                className={`block rounded border px-3 py-2 transition-colors ${
                  isSelected
                    ? "border-ink bg-surface"
                    : "border-rule bg-surface hover:border-rule-strong"
                }`}
              >
                <span className="flex items-center gap-1.5 text-[13px] font-medium">
                  v{entry.version}
                  {entry.is_active && (
                    <span className="flex items-center gap-1 text-[11px] font-medium text-pass">
                      <BadgeCheck size={12} aria-hidden="true" />
                      active
                    </span>
                  )}
                </span>
                <span className="tnum mt-0.5 block text-[11px] text-faint">
                  {entry.content_hash}
                </span>
                <span className="mt-0.5 block text-[11px] text-muted">
                  {new Date(entry.created_at + "Z").toLocaleString(undefined, {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
                {entry.note && (
                  <span className="mt-0.5 block text-[11px] leading-snug text-muted">
                    {entry.note}
                  </span>
                )}
              </Link>
            );
          })}
        </aside>

        <PolicyEditor
          assetType={assetType}
          version={selectedMeta}
          formValues={form?.values ?? null}
        />
      </div>
    </div>
  );
}
