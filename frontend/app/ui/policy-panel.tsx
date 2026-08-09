import Link from "next/link";
import { ChevronDown, ScrollText } from "lucide-react";
import { fetchPolicyVersions, fetchPolicyVersion, type AssetType } from "@/lib/api";

/**
 * The expandable "what governs this" panel shown on the evaluate and results pages.
 *
 * Collapsed it is one quiet line: class, version, hash. Open it is the full governing
 * document — the actual YAML, not a summary — because the policy IS the specification of
 * what runs and what passes, and paraphrasing it would reintroduce the ambiguity the
 * versioning exists to remove.
 */
export async function PolicyPanel({ assetType }: { assetType: AssetType }) {
  const versions = await fetchPolicyVersions(assetType);
  const active = versions?.find((v) => v.is_active);
  if (!active) return null;
  const full = await fetchPolicyVersion(assetType, active.version);
  if (!full) return null;

  return (
    <details className="group rounded-card border border-rule bg-surface">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-4 py-3 text-[12px] text-muted transition-colors hover:text-ink [&::-webkit-details-marker]:hidden">
        <ChevronDown
          size={14}
          className="transition-transform group-open:rotate-180"
          aria-hidden="true"
        />
        <ScrollText size={13} aria-hidden="true" />
        <span className="font-medium">
          Governing policy: {assetType.toUpperCase()} v{active.version}
        </span>
        <span className="tnum text-faint">({active.content_hash})</span>
        <span className="ml-auto text-[11px] text-faint">
          every run records the version that governed it
        </span>
      </summary>
      <div className="space-y-3 border-t border-rule px-4 py-4">
        <pre className="tnum max-h-96 overflow-auto rounded border border-rule bg-paper p-3 text-[11px] leading-relaxed">
          {full.content}
        </pre>
        <p className="text-[12px] text-muted">
          Editing creates a new immutable version; older versions stay viewable.{" "}
          <Link href={`/policies/${assetType}`} className="font-medium text-ink underline">
            History &amp; edit
          </Link>
        </p>
      </div>
    </details>
  );
}
