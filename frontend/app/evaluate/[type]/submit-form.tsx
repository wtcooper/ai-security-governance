"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createRun } from "@/lib/api";

/**
 * Models are a dropdown of gateway aliases, never a free-text field. That is what keeps a
 * provider-native model string from reaching a run, and with it the assumption of a direct
 * provider key.
 */
export function SubmitForm({
  models,
  defaultJudge,
}: {
  models: string[];
  defaultJudge: string;
}) {
  const router = useRouter();
  const subjectCandidates = models.filter((m) => !m.startsWith("mock-"));

  const [identifier, setIdentifier] = useState(subjectCandidates[0] ?? "");
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
      <p className="rounded border border-fail/40 bg-fail/10 px-4 py-3 text-sm text-fail">
        No models available from the gateway, so there is nothing to evaluate.
      </p>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded-lg border border-edge bg-surface p-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-1.5">
          <span className="block text-xs text-muted">Model (gateway alias)</span>
          <select
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            className="w-full rounded border border-edge bg-ink px-2 py-1.5 font-mono text-sm"
          >
            {subjectCandidates.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1.5">
          <span className="block text-xs text-muted">Judge / grader</span>
          <select
            value={judge}
            onChange={(e) => setJudge(e.target.value)}
            className="w-full rounded border border-edge bg-ink px-2 py-1.5 font-mono text-sm"
          >
            {models.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1.5">
          <span className="block text-xs text-muted">Display name (optional)</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={identifier}
            className="w-full rounded border border-edge bg-ink px-2 py-1.5 text-sm"
          />
        </label>

        <label className="space-y-1.5">
          <span className="block text-xs text-muted">
            Sample limit (optional, per benchmark)
          </span>
          <input
            value={limit}
            onChange={(e) => setLimit(e.target.value.replace(/\D/g, ""))}
            placeholder="registry default"
            className="w-full rounded border border-edge bg-ink px-2 py-1.5 text-sm"
          />
        </label>
      </div>

      <p className="text-xs text-muted">
        Subject and judge are both preflighted with a real completion before the run starts, so
        a broken model route fails immediately instead of part-way through.
      </p>

      {error && (
        <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded border border-fail/40 bg-fail/10 px-3 py-2 text-xs text-fail">
          {error}
        </pre>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="rounded bg-accent px-4 py-2 text-sm font-medium text-ink disabled:opacity-50"
      >
        {submitting ? "Preflighting and starting…" : "Start evaluation"}
      </button>
    </form>
  );
}
