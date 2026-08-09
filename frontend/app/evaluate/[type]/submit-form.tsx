"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Play } from "lucide-react";
import { createRun } from "@/lib/api";

/**
 * Models are a dropdown of gateway aliases, never a free-text field. That is what keeps a
 * provider-native model string from reaching a run, and with it the assumption of a direct
 * provider key.
 */
export function SubmitForm({
  models,
  defaultJudge,
  defaultSubject,
}: {
  models: string[];
  defaultJudge: string;
  defaultSubject: string;
}) {
  const router = useRouter();
  const subjectCandidates = models.filter((m) => !m.startsWith("mock-"));

  // Pre-select the backend's configured default, which is a local model. Falling back to
  // "whatever sorts first" previously landed on a paid model, so a mis-click billed a run.
  const [identifier, setIdentifier] = useState(
    subjectCandidates.includes(defaultSubject) ? defaultSubject : (subjectCandidates[0] ?? ""),
  );
  const [name, setName] = useState("");
  const [judge, setJudge] = useState(defaultJudge);
  const [limit, setLimit] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);

    const result = await createRun({
      asset_type: "llm",
      name: name.trim() || identifier,
      identifier,
      judge_model: judge,
      limit: limit ? Number(limit) : undefined,
    });

    if (!result.ok) {
      setError(result.error);
      setSubmitting(false);
      return;
    }
    router.push(`/runs/${result.run.id}`);
  }

  if (models.length === 0) {
    return (
      <p className="rounded-card border border-block/30 bg-block-wash px-4 py-3 text-[13px] text-block">
        No models available from the gateway, so there is nothing to evaluate.
      </p>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5 rounded-card border border-rule bg-surface p-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-1.5">
          <span className="eyebrow block">Model (gateway alias)</span>
          <select
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            className="tnum w-full rounded border border-rule bg-surface px-2.5 py-2 text-[13px]"
          >
            {subjectCandidates.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1.5">
          <span className="eyebrow block">Judge / grader</span>
          <select
            value={judge}
            onChange={(e) => setJudge(e.target.value)}
            className="tnum w-full rounded border border-rule bg-surface px-2.5 py-2 text-[13px]"
          >
            {models.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1.5">
          <span className="eyebrow block">Display name (optional)</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={identifier}
            className="w-full rounded border border-rule bg-surface px-2.5 py-2 text-[13px]"
          />
        </label>

        <label className="space-y-1.5">
          <span className="eyebrow block">Sample override (dev only, optional)</span>
          <input
            value={limit}
            onChange={(e) => setLimit(e.target.value.replace(/\D/g, ""))}
            placeholder="policy decides — leave empty"
            className="w-full rounded border border-rule bg-surface px-2.5 py-2 text-[13px]"
          />
        </label>
      </div>

      <p className="text-[12px] leading-relaxed text-muted">
        How many samples each benchmark runs comes from the governing policy — see the panel
        below. The override exists for cheap wiring checks; a run that uses it is flagged on
        every results view and should never be read as a governance result.
      </p>

      <p className="text-[12px] leading-relaxed text-muted">
        Subject and judge are both preflighted with a real completion before the run starts, so
        a broken model route fails immediately instead of part-way through.
      </p>

      {error && (
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded border border-block/30 bg-block-wash px-3 py-2 text-[11px] leading-relaxed text-block">
          {error}
        </pre>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="inline-flex items-center gap-2 rounded bg-ink px-4 py-2 text-[13px] font-medium text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
      >
        <Play size={13} strokeWidth={2.5} aria-hidden="true" />
        {submitting ? "Preflighting and starting…" : "Start evaluation"}
      </button>
    </form>
  );
}
