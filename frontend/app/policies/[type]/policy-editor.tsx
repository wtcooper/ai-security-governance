"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Code, Lock, Pin, Save, SlidersHorizontal } from "lucide-react";
import {
  createPolicyVersion,
  createPolicyVersionFromForm,
  type AssetType,
  type LlmFormValues,
  type PolicyVersionOut,
  type ScannerFormValues,
} from "@/lib/api";

const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const;

/**
 * Viewing one version; editing only ever means "save as the next version".
 *
 * The form is the primary editor: key settings (thresholds, sample counts, judge, severity
 * rules) as typed fields, applied server-side to the current document with its comments
 * intact. Raw YAML editing remains as the advanced path — it is the only way to add a
 * gate or hand-tune a core set, and some edits are genuinely textual. Both paths run the
 * same server-side validation, and superseded versions open read-only either way.
 */
export function PolicyEditor({
  assetType,
  version,
  formValues,
}: {
  assetType: AssetType;
  version: PolicyVersionOut;
  formValues: LlmFormValues | ScannerFormValues | null;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<"view" | "form" | "yaml">("view");
  const [content, setContent] = useState(version.content);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function onSaved(newVersion: number) {
    setMode("view");
    setSaving(false);
    setNote("");
    router.push(`/policies/${assetType}?v=${newVersion}`);
    router.refresh();
  }

  async function onSaveYaml() {
    setSaving(true);
    setError(null);
    const result = await createPolicyVersion(assetType, content, note);
    if (!result.ok) {
      setError(result.error);
      setSaving(false);
      return;
    }
    onSaved(result.data.version);
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
          mode === "view" && (
            <div className="flex gap-2">
              <button
                onClick={() => setMode("form")}
                className="inline-flex items-center gap-1.5 rounded bg-ink px-3 py-1.5 text-[12px] font-medium text-paper transition-opacity hover:opacity-90"
              >
                <SlidersHorizontal size={12} aria-hidden="true" />
                Edit settings
              </button>
              <button
                onClick={() => {
                  setContent(version.content);
                  setMode("yaml");
                }}
                className="inline-flex items-center gap-1.5 rounded border border-rule px-3 py-1.5 text-[12px] font-medium text-muted transition-colors hover:border-ink hover:text-ink"
              >
                <Code size={12} aria-hidden="true" />
                Edit raw YAML
              </button>
            </div>
          )
        ) : (
          <span className="flex items-center gap-1.5 text-[12px] text-muted">
            <Lock size={12} aria-hidden="true" />
            superseded — read only
          </span>
        )}
      </div>

      {mode === "form" && formValues && (
        <>
          {assetType === "llm" ? (
            <LlmForm
              initial={formValues as LlmFormValues}
              note={note}
              setNote={setNote}
              error={error}
              setError={setError}
              saving={saving}
              setSaving={setSaving}
              onSaved={onSaved}
              nextVersion={version.version + 1}
              onCancel={() => {
                setMode("view");
                setError(null);
              }}
            />
          ) : (
            <ScannerForm
              assetType={assetType}
              initial={formValues as ScannerFormValues}
              note={note}
              setNote={setNote}
              error={error}
              setError={setError}
              saving={saving}
              setSaving={setSaving}
              onSaved={onSaved}
              nextVersion={version.version + 1}
              onCancel={() => {
                setMode("view");
                setError(null);
              }}
            />
          )}
        </>
      )}

      {mode === "yaml" && (
        <div className="space-y-3">
          <p className="text-[12px] leading-relaxed text-muted">
            The advanced path: full control of the document, including adding gates and
            hand-editing core sets. Validated on save exactly like the form.
          </p>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={24}
            spellCheck={false}
            className="tnum w-full rounded border border-rule bg-surface p-3 text-[12px] leading-relaxed"
          />
          <NoteField note={note} setNote={setNote} />
          <FormError error={error} />
          <SaveRow
            saving={saving}
            nextVersion={version.version + 1}
            onSave={onSaveYaml}
            onCancel={() => {
              setMode("view");
              setError(null);
            }}
          />
        </div>
      )}

      {mode === "view" && (
        <pre className="tnum max-h-[36rem] overflow-auto rounded-card border border-rule bg-surface p-4 text-[12px] leading-relaxed">
          {version.content}
        </pre>
      )}
    </section>
  );
}

// --- shared bits --------------------------------------------------------------------------

function NoteField({ note, setNote }: { note: string; setNote: (v: string) => void }) {
  return (
    <label className="block space-y-1.5">
      <span className="eyebrow block">Why this change (saved with the version)</span>
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="e.g. tighten prompt-injection threshold after calibration"
        className="w-full rounded border border-rule bg-surface px-2.5 py-2 text-[13px]"
      />
    </label>
  );
}

function FormError({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded border border-block/30 bg-block-wash px-3 py-2 text-[11px] leading-relaxed text-block">
      {error}
    </pre>
  );
}

function SaveRow({
  saving,
  nextVersion,
  onSave,
  onCancel,
}: {
  saving: boolean;
  nextVersion: number;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex gap-2">
      <button
        onClick={onSave}
        disabled={saving}
        className="inline-flex items-center gap-2 rounded bg-ink px-4 py-2 text-[13px] font-medium text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
      >
        <Save size={13} strokeWidth={2.5} aria-hidden="true" />
        {saving ? "Validating and saving…" : `Save as v${nextVersion}`}
      </button>
      <button
        onClick={onCancel}
        className="rounded border border-rule px-4 py-2 text-[13px] text-muted transition-colors hover:text-ink"
      >
        Cancel
      </button>
    </div>
  );
}

function fieldClass(width = "w-24") {
  return `tnum ${width} rounded border border-rule bg-surface px-2.5 py-1.5 text-[13px]`;
}

// --- LLM form -----------------------------------------------------------------------------

type SharedFormProps = {
  note: string;
  setNote: (v: string) => void;
  error: string | null;
  setError: (v: string | null) => void;
  saving: boolean;
  setSaving: (v: boolean) => void;
  onSaved: (version: number) => void;
  nextVersion: number;
  onCancel: () => void;
};

function LlmForm({
  initial,
  note,
  setNote,
  error,
  setError,
  saving,
  setSaving,
  onSaved,
  nextVersion,
  onCancel,
}: SharedFormProps & { initial: LlmFormValues }) {
  const [judgeModel, setJudgeModel] = useState(initial.judge_default_model);
  const [maxRefusal, setMaxRefusal] = useState(String(initial.judge_max_refusal_rate));
  const [gates, setGates] = useState(
    Object.fromEntries(
      Object.entries(initial.gates).map(([id, g]) => [
        id,
        { threshold: String(g.threshold), samples: String(g.samples), clearPin: false },
      ]),
    ),
  );
  const [weights, setWeights] = useState(
    Object.fromEntries(
      Object.entries(initial.composite_weights).map(([id, w]) => [id, String(w)]),
    ),
  );
  const [blockUnsafe, setBlockUnsafe] = useState(initial.weights_block_on_unsafe_file);
  const [unscannedPass, setUnscannedPass] = useState(initial.weights_treat_unscanned_as_pass);

  async function onSave() {
    setSaving(true);
    setError(null);
    const result = await createPolicyVersionFromForm("llm", {
      judge_default_model: judgeModel.trim(),
      judge_max_refusal_rate: Number(maxRefusal),
      gates: Object.fromEntries(
        Object.entries(gates).map(([id, g]) => [
          id,
          {
            threshold: Number(g.threshold),
            samples: Number(g.samples),
            clear_sample_ids: g.clearPin,
          },
        ]),
      ),
      composite_weights: Object.fromEntries(
        Object.entries(weights).map(([id, w]) => [id, Number(w)]),
      ),
      weights_block_on_unsafe_file: blockUnsafe,
      weights_treat_unscanned_as_pass: unscannedPass,
      note,
    });
    if (!result.ok) {
      setError(result.error);
      setSaving(false);
      return;
    }
    onSaved(result.data.version);
  }

  return (
    <div className="space-y-5">
      <div className="rounded-card border border-rule bg-surface p-4">
        <h3 className="eyebrow mb-3">Judge</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1.5">
            <span className="block text-[12px] text-muted">Default judge model (gateway alias)</span>
            <input
              value={judgeModel}
              onChange={(e) => setJudgeModel(e.target.value)}
              className={fieldClass("w-full")}
            />
          </label>
          <label className="space-y-1.5">
            <span className="block text-[12px] text-muted">
              Max unresolved-verdict rate before the run is voided
            </span>
            <input
              value={maxRefusal}
              onChange={(e) => setMaxRefusal(e.target.value)}
              className={fieldClass()}
            />
          </label>
        </div>
      </div>

      <div className="overflow-x-auto rounded-card border border-rule bg-surface">
        <table className="w-full min-w-[38rem] border-collapse">
          <thead>
            <tr className="border-b border-rule">
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Gate</th>
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Threshold</th>
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Samples</th>
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Weight</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(initial.gates).map(([id, meta]) => (
              <tr key={id} className="border-b border-rule align-top last:border-0">
                <td className="px-4 py-3">
                  <div className="tnum text-[12px] font-medium">{id}</div>
                  <div className="mt-0.5 text-[11px] text-muted">
                    {meta.metric} · {meta.direction === "higher_is_better" ? "≥" : "≤"} passes
                  </div>
                </td>
                <td className="px-4 py-3">
                  <input
                    value={gates[id].threshold}
                    onChange={(e) =>
                      setGates({ ...gates, [id]: { ...gates[id], threshold: e.target.value } })
                    }
                    className={fieldClass("w-20")}
                    aria-label={`${id} threshold`}
                  />
                </td>
                <td className="px-4 py-3">
                  <input
                    value={gates[id].samples}
                    onChange={(e) =>
                      setGates({
                        ...gates,
                        [id]: { ...gates[id], samples: e.target.value.replace(/\D/g, "") },
                      })
                    }
                    className={fieldClass("w-20")}
                    aria-label={`${id} samples`}
                  />
                  {meta.sample_ids_count > 0 && (
                    <label className="mt-1.5 flex items-center gap-1.5 text-[11px]">
                      <span className="flex items-center gap-1 font-medium text-pass">
                        <Pin size={10} aria-hidden="true" />
                        {meta.sample_ids_count} pinned
                      </span>
                      <input
                        type="checkbox"
                        checked={gates[id].clearPin}
                        onChange={(e) =>
                          setGates({
                            ...gates,
                            [id]: { ...gates[id], clearPin: e.target.checked },
                          })
                        }
                      />
                      <span className="text-muted">unpin core set</span>
                    </label>
                  )}
                </td>
                <td className="px-4 py-3">
                  <input
                    value={weights[id] ?? ""}
                    onChange={(e) => setWeights({ ...weights, [id]: e.target.value })}
                    className={fieldClass("w-20")}
                    aria-label={`${id} composite weight`}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] leading-relaxed text-muted">
        Metric and direction are facts about each benchmark, not preferences — they are not
        editable here (or in raw YAML: the validator pins them to the registry). Weights
        order the results table only; they never gate. A pinned core set keeps governing
        until unpinned, at which point the samples count applies.
      </p>

      <div className="rounded-card border border-rule bg-surface p-4">
        <h3 className="eyebrow mb-3">Open-weight supply chain</h3>
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-[12px]">
            <input
              type="checkbox"
              checked={blockUnsafe}
              onChange={(e) => setBlockUnsafe(e.target.checked)}
            />
            Block when any scanner calls any weight file unsafe
          </label>
          <label className="flex items-center gap-2 text-[12px]">
            <input
              type="checkbox"
              checked={unscannedPass}
              onChange={(e) => setUnscannedPass(e.target.checked)}
            />
            Treat unscanned repositories as passing{" "}
            <span className="text-muted">(not recommended — unscanned is not safe)</span>
          </label>
        </div>
      </div>

      <NoteField note={note} setNote={setNote} />
      <FormError error={error} />
      <SaveRow saving={saving} nextVersion={nextVersion} onSave={onSave} onCancel={onCancel} />
    </div>
  );
}

// --- Scanner form -------------------------------------------------------------------------

function ScannerForm({
  assetType,
  initial,
  note,
  setNote,
  error,
  setError,
  saving,
  setSaving,
  onSaved,
  nextVersion,
  onCancel,
}: SharedFormProps & { assetType: AssetType; initial: ScannerFormValues }) {
  const [mode, setMode] = useState(initial.mode);
  const [blockOn, setBlockOn] = useState<string[]>(initial.block_on);
  const [trust, setTrust] = useState(initial.trust_scanner_verdict);
  const [penalty, setPenalty] = useState(
    Object.fromEntries(SEVERITIES.map((s) => [s, String(initial.severity_rollup_penalty[s] ?? 0)])),
  );

  async function onSave() {
    setSaving(true);
    setError(null);
    const result = await createPolicyVersionFromForm(assetType, {
      mode,
      block_on: blockOn,
      trust_scanner_verdict: trust,
      severity_rollup_penalty: Object.fromEntries(
        Object.entries(penalty).map(([s, v]) => [s, Number(v)]),
      ),
      note,
    });
    if (!result.ok) {
      setError(result.error);
      setSaving(false);
      return;
    }
    onSaved(result.data.version);
  }

  return (
    <div className="space-y-5">
      <div className="rounded-card border border-rule bg-surface p-4">
        <h3 className="eyebrow mb-3">Decision mode</h3>
        <div className="space-y-2">
          <label className="flex items-start gap-2 text-[12px]">
            <input
              type="radio"
              name="mode"
              checked={mode === "advisory"}
              onChange={() => setMode("advisory")}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium">Advisory</span>{" "}
              <span className="text-muted">
                — every result goes to human review; nothing is auto-approved. The safe
                setting while the severity rule has no false-positive baseline.
              </span>
            </span>
          </label>
          <label className="flex items-start gap-2 text-[12px]">
            <input
              type="radio"
              name="mode"
              checked={mode === "gating"}
              onChange={() => setMode("gating")}
              className="mt-0.5"
            />
            <span>
              <span className="font-medium">Gating</span>{" "}
              <span className="text-muted">
                — a clean scan auto-approves. Flip only once the severity distribution shows
                the rule discriminates rather than firing on everything.
              </span>
            </span>
          </label>
        </div>
      </div>

      <div className="rounded-card border border-rule bg-surface p-4">
        <h3 className="eyebrow mb-3">Blocking severities</h3>
        <div className="flex flex-wrap gap-4">
          {SEVERITIES.map((severity) => (
            <label key={severity} className="flex items-center gap-1.5 text-[12px]">
              <input
                type="checkbox"
                checked={blockOn.includes(severity)}
                onChange={(e) =>
                  setBlockOn(
                    e.target.checked
                      ? [...blockOn, severity]
                      : blockOn.filter((s) => s !== severity),
                  )
                }
              />
              <span className="tnum">{severity}</span>
            </label>
          ))}
        </div>
        <label className="mt-3 flex items-center gap-2 text-[12px]">
          <input type="checkbox" checked={trust} onChange={(e) => setTrust(e.target.checked)} />
          Honour the scanner&apos;s own overall verdict where it has one
        </label>
      </div>

      <div className="rounded-card border border-rule bg-surface p-4">
        <h3 className="eyebrow mb-3">Severity roll-up (orders the results table; never gates)</h3>
        <div className="flex flex-wrap gap-4">
          {SEVERITIES.map((severity) => (
            <label key={severity} className="space-y-1">
              <span className="tnum block text-[11px] text-muted">{severity}</span>
              <input
                value={penalty[severity]}
                onChange={(e) =>
                  setPenalty({ ...penalty, [severity]: e.target.value.replace(/\D/g, "") })
                }
                className={fieldClass("w-16")}
                aria-label={`${severity} penalty`}
              />
            </label>
          ))}
        </div>
      </div>

      <NoteField note={note} setNote={setNote} />
      <FormError error={error} />
      <SaveRow saving={saving} nextVersion={nextVersion} onSave={onSave} onCancel={onCancel} />
    </div>
  );
}
