import Link from "next/link";
import { ArrowRight, ScrollText } from "lucide-react";
import { fetchPolicyVersions, type AssetType } from "@/lib/api";

/**
 * One quiet line stating which policy version governs this asset class, with the way to
 * read or change it.
 *
 * Deliberately not an expander and deliberately not the document: the full settings live on
 * the criteria and policy pages, where there is room to lay them out as a record. A panel
 * that unfolded raw YAML made the policy look like a config file to be parsed rather than a
 * decision to be understood.
 */
export async function PolicyPanel({ assetType }: { assetType: AssetType }) {
  const versions = await fetchPolicyVersions(assetType);
  const active = versions?.find((v) => v.is_active);
  if (!active) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-card border border-rule bg-surface px-4 py-3 text-[12px]">
      <ScrollText size={13} className="text-faint" aria-hidden="true" />
      <span className="font-medium">
        Governed by {assetType.toUpperCase()} policy v{active.version}
      </span>
      <span className="tnum text-faint">{active.content_hash}</span>
      <span className="text-muted">— every run records the version that governed it</span>
      <Link
        href={`/policies/${assetType}`}
        className="group ml-auto flex items-center gap-1 font-medium text-ink hover:underline"
      >
        Settings &amp; history
        <ArrowRight
          size={12}
          className="transition-transform group-hover:translate-x-0.5"
          aria-hidden="true"
        />
      </Link>
    </div>
  );
}
