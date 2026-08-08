"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ScanSearch } from "lucide-react";
import { createRun, type AssetType } from "@/lib/api";

/**
 * Submitting an MCP server or agent skill for scanning.
 *
 * Only https URLs on known forges are accepted, and the repository is cloned read-only —
 * nothing from a submission is ever executed. That constraint is stated here rather than
 * buried, because it is also the reason detection has limits.
 */
export function ScannerForm({
  assetType,
  analyzerModel,
}: {
  assetType: Extract<AssetType, "mcp" | "skill">;
  analyzerModel: string;
}) {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    const result = await createRun({
      asset_type: assetType,
      name: name.trim() || identifier.replace(/^https:\/\//, ""),
      identifier: identifier.trim(),
    });

    if (!result.ok) {
      setError(result.error);
      setSubmitting(false);
      return;
    }
    router.push(`/runs/${result.run.id}`);
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5 rounded-card border border-rule bg-surface p-5">
      <label className="block space-y-1.5">
        <span className="eyebrow block">Repository URL</span>
        <input
          value={identifier}
          onChange={(e) => setIdentifier(e.target.value)}
          placeholder="https://github.com/owner/repo"
          required
          className="tnum w-full rounded border border-rule bg-surface px-2.5 py-2 text-[13px]"
        />
      </label>

      <label className="block space-y-1.5">
        <span className="eyebrow block">Display name (optional)</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded border border-rule bg-surface px-2.5 py-2 text-[13px]"
        />
      </label>

      <div className="space-y-1.5 text-[12px] leading-relaxed text-muted">
        <p>
          The repository is shallow-cloned and analysed statically. Nothing in it is ever
          executed, and its git hooks are disabled.
        </p>
        <p>
          Analyzer model: <span className="tnum">{analyzerModel}</span> via the gateway.
        </p>
      </div>

      {error && (
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded border border-block/30 bg-block-wash px-3 py-2 text-[11px] leading-relaxed text-block">
          {error}
        </pre>
      )}

      <button
        type="submit"
        disabled={submitting || !identifier.trim()}
        className="inline-flex items-center gap-2 rounded bg-ink px-4 py-2 text-[13px] font-medium text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
      >
        <ScanSearch size={13} strokeWidth={2.5} aria-hidden="true" />
        {submitting ? "Cloning and scanning…" : "Start scan"}
      </button>
    </form>
  );
}
