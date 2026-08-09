"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ScanSearch, Upload } from "lucide-react";
import { createRun, uploadArchive, type AssetType } from "@/lib/api";

/**
 * Submitting an MCP server or agent skill for scanning.
 *
 * Two sources, because not every artifact lives somewhere clonable: a repository URL
 * (https, known forges only), or a zip upload for code that sits behind an enterprise
 * boundary. Either way the source is analysed read-only — nothing from a submission is
 * ever executed. That constraint is stated here rather than buried, because it is also the
 * reason detection has limits.
 */
export function ScannerForm({
  assetType,
  analyzerModel,
}: {
  assetType: Extract<AssetType, "mcp" | "skill">;
  analyzerModel: string;
}) {
  const router = useRouter();
  const [source, setSource] = useState<"url" | "zip">("url");
  const [identifier, setIdentifier] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    let runIdentifier = identifier.trim();
    let fallbackName = runIdentifier.replace(/^https:\/\//, "");

    if (source === "zip") {
      if (!file) {
        setError("Choose a .zip archive first.");
        setSubmitting(false);
        return;
      }
      const uploaded = await uploadArchive(file);
      if (!uploaded.ok) {
        setError(uploaded.error);
        setSubmitting(false);
        return;
      }
      runIdentifier = uploaded.identifier;
      fallbackName = uploaded.filename.replace(/\.zip$/i, "");
    }

    const result = await createRun({
      asset_type: assetType,
      name: name.trim() || fallbackName,
      identifier: runIdentifier,
    });

    if (!result.ok) {
      setError(result.error);
      setSubmitting(false);
      return;
    }
    router.push(`/runs/${result.run.id}`);
  }

  const ready = source === "url" ? identifier.trim().length > 0 : file !== null;

  return (
    <form onSubmit={onSubmit} className="space-y-5 rounded-card border border-rule bg-surface p-5">
      <fieldset className="space-y-1.5">
        <legend className="eyebrow">Source</legend>
        <div className="flex gap-2" role="radiogroup">
          {(
            [
              ["url", "Repository URL"],
              ["zip", "Zip upload"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={source === value}
              onClick={() => {
                setSource(value);
                setError(null);
              }}
              className={`rounded border px-3 py-1.5 text-[12px] font-medium transition-colors ${
                source === value
                  ? "border-ink bg-ink text-paper"
                  : "border-rule text-muted hover:border-ink hover:text-ink"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </fieldset>

      {source === "url" ? (
        <label className="block space-y-1.5">
          <span className="eyebrow block">Repository URL</span>
          <input
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            placeholder="https://github.com/owner/repo"
            className="tnum w-full rounded border border-rule bg-surface px-2.5 py-2 text-[13px]"
          />
        </label>
      ) : (
        <label className="block space-y-1.5">
          <span className="eyebrow block">Zip archive</span>
          <input
            type="file"
            accept=".zip"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="w-full rounded border border-rule bg-surface px-2.5 py-2 text-[13px] file:mr-3 file:rounded file:border-0 file:bg-paper file:px-3 file:py-1 file:text-[12px] file:font-medium"
          />
          <span className="block text-[11px] text-muted">
            For sources this machine cannot clone — enterprise GitHub, internal registries.
            Extracted with path validation; never executed.
          </span>
        </label>
      )}

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
          {source === "url"
            ? "The repository is shallow-cloned and analysed statically. Nothing in it is ever executed, and its git hooks are disabled."
            : "The archive is extracted into an isolated workspace and analysed statically. Nothing in it is ever executed."}
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
        disabled={submitting || !ready}
        className="inline-flex items-center gap-2 rounded bg-ink px-4 py-2 text-[13px] font-medium text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
      >
        {source === "zip" ? (
          <Upload size={13} strokeWidth={2.5} aria-hidden="true" />
        ) : (
          <ScanSearch size={13} strokeWidth={2.5} aria-hidden="true" />
        )}
        {submitting
          ? source === "zip"
            ? "Uploading and scanning…"
            : "Cloning and scanning…"
          : "Start scan"}
      </button>
    </form>
  );
}
