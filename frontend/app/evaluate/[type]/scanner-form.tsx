"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
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
    <form onSubmit={onSubmit} className="space-y-4 rounded-lg border border-edge bg-surface p-5">
      <label className="block space-y-1.5">
        <span className="block text-xs text-muted">Repository URL</span>
        <input
          value={identifier}
          onChange={(e) => setIdentifier(e.target.value)}
          placeholder="https://github.com/owner/repo"
          required
          className="w-full rounded border border-edge bg-ink px-2 py-1.5 font-mono text-sm"
        />
      </label>

      <label className="block space-y-1.5">
        <span className="block text-xs text-muted">Display name (optional)</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded border border-edge bg-ink px-2 py-1.5 text-sm"
        />
      </label>

      <div className="space-y-1 text-xs text-muted">
        <p>
          The repository is shallow-cloned and analysed statically. Nothing in it is ever
          executed, and its git hooks are disabled.
        </p>
        <p>
          Analyzer model: <span className="font-mono">{analyzerModel}</span> via the gateway.
        </p>
      </div>

      {error && (
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded border border-fail/40 bg-fail/10 px-3 py-2 text-xs text-fail">
          {error}
        </pre>
      )}

      <button
        type="submit"
        disabled={submitting || !identifier.trim()}
        className="rounded bg-accent px-4 py-2 text-sm font-medium text-ink disabled:opacity-50"
      >
        {submitting ? "Cloning and scanning…" : "Start scan"}
      </button>
    </form>
  );
}
