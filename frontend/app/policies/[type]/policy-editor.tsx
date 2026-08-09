"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Lock, Save } from "lucide-react";
import { createPolicyVersion, type AssetType, type PolicyVersionOut } from "@/lib/api";

/**
 * Viewing one version; editing only ever means "save as the next version".
 *
 * Superseded versions open read-only — the textarea only appears for the active version,
 * which is the only place an edit can meaningfully start from. Validation happens
 * server-side against the benchmark registry, and a rejected save creates nothing.
 */
export function PolicyEditor({
  assetType,
  version,
}: {
  assetType: AssetType;
  version: PolicyVersionOut;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(version.content);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function onSave() {
    setSaving(true);
    setError(null);
    const result = await createPolicyVersion(assetType, content, note);
    if (!result.ok) {
      setError(result.error);
      setSaving(false);
      return;
    }
    setEditing(false);
    setSaving(false);
    setNote("");
    router.push(`/policies/${assetType}?v=${result.data.version}`);
    router.refresh();
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-semibold tracking-tight">
            {assetType.toUpperCase()} policy v{version.version}
          </h2>
          <p className="tnum mt-0.5 text-[11px] text-faint">{version.content_hash}</p>
        </div>
        {version.is_active ? (
          !editing && (
            <button
              onClick={() => {
                setContent(version.content);
                setEditing(true);
              }}
              className="inline-flex items-center gap-1.5 rounded border border-rule px-3 py-1.5 text-[12px] font-medium transition-colors hover:border-ink"
            >
              Edit as v{version.version + 1}
            </button>
          )
        ) : (
          <span className="flex items-center gap-1.5 text-[12px] text-muted">
            <Lock size={12} aria-hidden="true" />
            superseded — read only
          </span>
        )}
      </div>

      {editing ? (
        <div className="space-y-3">
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={24}
            spellCheck={false}
            className="tnum w-full rounded border border-rule bg-surface p-3 text-[12px] leading-relaxed"
          />
          <label className="block space-y-1.5">
            <span className="eyebrow block">Why this change (saved with the version)</span>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. adopt fixed core set for prompt injection, n=50"
              className="w-full rounded border border-rule bg-surface px-2.5 py-2 text-[13px]"
            />
          </label>
          {error && (
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded border border-block/30 bg-block-wash px-3 py-2 text-[11px] leading-relaxed text-block">
              {error}
            </pre>
          )}
          <div className="flex gap-2">
            <button
              onClick={onSave}
              disabled={saving}
              className="inline-flex items-center gap-2 rounded bg-ink px-4 py-2 text-[13px] font-medium text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              <Save size={13} strokeWidth={2.5} aria-hidden="true" />
              {saving ? "Validating and saving…" : `Save as v${version.version + 1}`}
            </button>
            <button
              onClick={() => {
                setEditing(false);
                setError(null);
              }}
              className="rounded border border-rule px-4 py-2 text-[13px] text-muted transition-colors hover:text-ink"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <pre className="tnum max-h-[36rem] overflow-auto rounded-card border border-rule bg-surface p-4 text-[12px] leading-relaxed">
          {version.content}
        </pre>
      )}
    </section>
  );
}
