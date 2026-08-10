"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Lock, Pin, Save, SlidersHorizontal } from "lucide-react";
import { PolicySettings } from "../../ui/policy-settings";
import { ASSET } from "../../ui/vocabulary";
import {
  createPolicyVersionFromForm,
  type AssetType,
  type LlmFormValues,
  type PolicyVersionMeta,
  type ScannerFormValues,
} from "@/lib/api";

const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const;

/**
 * Viewing one version; editing only ever means "save as the next version".
 *
 * Settings are the whole interface: typed fields for thresholds, sample counts, which
 * benchmarks are in the suite, the judge, and the scanner severity rules. There is no YAML
 * surface — the document remains the storage and audit format, but nobody has to read or
 * hand-indent it to change a threshold. Edits are applied server-side to the current
 * document (comments preserved), validated against the benchmark registry, and saved as the
 * next immutable version. Superseded versions render the same settings, read-only.
 */
export function PolicyEditor({
  assetType,
  version,
  formValues,
}: {
  assetType: AssetType;
  version: PolicyVersionMeta;
  formValues: LlmFormValues | ScannerFormValues | null;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<"view" | "form">("view");
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

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-semibold tracking-tight">
            {ASSET[assetType].label} policy v{version.version}
          </h2>
          <p className="tnum mt-0.5 text-[11px] text-faint">{version.content_hash}</p>
        </div>
        {version.is_active ? (
          mode === "view" && (
            <button
              onClick={() => setMode("form")}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition-opacity hover:opacity-90"
            >
              <SlidersHorizontal size={12} aria-hidden="true" />
              Edit settings
            </button>
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

      {mode === "view" &&
        (formValues ? (
          <PolicySettings assetType={assetType} values={formValues} />
        ) : (
          <p className="rounded-card border border-rule bg-surface px-4 py-6 text-center text-[12px] text-muted">
            Settings for this version could not be read.
          </p>
        ))}
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
        className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
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
        {
          enabled: g.enabled,
          threshold: String(g.threshold),
          samples: String(g.samples),
          weight: String(g.weight),
          clearPin: false,
        },
      ]),
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
            enabled: g.enabled,
            threshold: Number(g.threshold),
            samples: Number(g.samples),
            weight: Number(g.weight),
            clear_sample_ids: g.clearPin,
          },
        ]),
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

  const depth = initial.depth_presets ?? [];
  // Which preset the current numbers correspond to, if any. Editing one gate by hand leaves
  // this null rather than mislabelling a bespoke configuration as a preset.
  const activeDepth =
    depth.find((preset) =>
      Object.entries(preset.per_check).every(
        ([id, n]) => gates[id] && Number(gates[id].samples) === n,
      ),
    )?.key ?? null;

  function applyDepth(preset: (typeof depth)[number]) {
    setGates(
      Object.fromEntries(
        Object.entries(gates).map(([id, g]) => [
          id,
          id in preset.per_check ? { ...g, samples: String(preset.per_check[id]) } : g,
        ]),
      ),
    );
  }

  return (
    <div className="space-y-5">
      <div className="rounded-card border border-rule bg-surface p-4">
        <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="eyebrow">How much to measure</h3>
          <span className="text-[11px] text-muted">
            the biggest cost lever, and what separates a wiring check from a signal
          </span>
        </div>
        <div className="mt-3 grid gap-px overflow-hidden rounded border border-rule bg-rule sm:grid-cols-3">
          {depth.map((preset) => {
            const isActive = activeDepth === preset.key;
            return (
              <button
                key={preset.key}
                type="button"
                onClick={() => applyDepth(preset)}
                aria-pressed={isActive}
                className={`space-y-1 p-3 text-left transition-colors ${
                  isActive ? "bg-accent text-white" : "bg-surface hover:bg-paper"
                }`}
              >
                <span className="flex items-baseline justify-between gap-2">
                  <span className="text-[13px] font-medium">{preset.label}</span>
                  <span className={`tnum text-[11px] ${isActive ? "text-white/70" : "text-faint"}`}>
                    {preset.samples == null ? "full datasets" : `n=${preset.samples}`}
                  </span>
                </span>
                <span className="tnum block text-[12px]">
                  {preset.total_tests.toLocaleString()} tests
                  <span className={isActive ? "text-white/70" : "text-faint"}>
                    {" "}
                    · ~{preset.total_calls.toLocaleString()} calls
                  </span>
                </span>
                <span
                  className={`block text-[11px] leading-relaxed ${
                    isActive ? "text-white/80" : "text-muted"
                  }`}
                >
                  {preset.blurb}
                </span>
              </button>
            );
          })}
        </div>
        {activeDepth === null && (
          <p className="mt-2 text-[11px] text-muted">
            Custom sample counts — not one of the presets. Per-benchmark values are below.
          </p>
        )}
      </div>

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
        <table className="w-full min-w-[42rem] border-collapse">
          <thead>
            <tr className="border-b border-rule">
              <th className="eyebrow px-4 py-2.5 text-left font-medium">In suite</th>
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Benchmark</th>
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Threshold</th>
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Samples</th>
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Weight</th>
              <th className="eyebrow px-4 py-2.5 text-left font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(initial.gates).map(([id, meta]) => {
              const on = gates[id].enabled;
              const calls = Number(gates[id].samples || 0) * meta.calls_per_sample;
              return (
                <tr
                  key={id}
                  className={`border-b border-rule align-top last:border-0 ${
                    on ? "" : "opacity-55"
                  }`}
                >
                  <td className="px-4 py-3">
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={(e) =>
                        setGates({ ...gates, [id]: { ...gates[id], enabled: e.target.checked } })
                      }
                      aria-label={`include ${id}`}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="tnum text-[12px] font-medium">{id}</div>
                    <div className="mt-0.5 text-[11px] text-muted">
                      {meta.metric} · {meta.direction === "higher_is_better" ? "≥" : "≤"} passes
                      {meta.needs_judge && " · needs judge"}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <input
                      value={gates[id].threshold}
                      disabled={!on}
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
                      disabled={!on}
                      onChange={(e) =>
                        setGates({
                          ...gates,
                          [id]: { ...gates[id], samples: e.target.value.replace(/\D/g, "") },
                        })
                      }
                      className={fieldClass("w-20")}
                      aria-label={`${id} samples`}
                    />
                    <div className="tnum mt-0.5 text-[11px] text-faint">
                      of {meta.dataset_max}
                    </div>
                    {meta.sample_ids_count > 0 && (
                      <label className="mt-1.5 flex items-center gap-1.5 text-[11px]">
                        <span className="flex items-center gap-1 font-medium text-pass">
                          <Pin size={10} aria-hidden="true" />
                          {meta.sample_ids_count} pinned
                        </span>
                        <input
                          type="checkbox"
                          checked={gates[id].clearPin}
                          disabled={!on}
                          onChange={(e) =>
                            setGates({
                              ...gates,
                              [id]: { ...gates[id], clearPin: e.target.checked },
                            })
                          }
                        />
                        <span className="text-muted">unpin</span>
                      </label>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <input
                      value={gates[id].weight}
                      disabled={!on}
                      onChange={(e) =>
                        setGates({ ...gates, [id]: { ...gates[id], weight: e.target.value } })
                      }
                      className={fieldClass("w-20")}
                      aria-label={`${id} composite weight`}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="tnum text-[12px]">
                      {on ? `~${calls}` : "—"}
                      <span className="text-faint"> calls</span>
                    </div>
                    <div className="tnum mt-0.5 text-[11px] text-faint">
                      {meta.calls_per_sample}/sample
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] leading-relaxed text-muted">
        Unticking a benchmark removes it from the suite; ticking one adds it, taking its
        metric and direction from the benchmark registry — those are facts about the
        benchmark, not preferences, so they are never editable. Weights order the results
        table only; they never gate. A pinned core set keeps governing until unpinned, at
        which point the samples count applies. Cost is model calls per run, so the expense is
        visible before starting rather than discovered during.
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
  const [blockOn, setBlockOn] = useState<string[]>(initial.block_on);
  const [trust, setTrust] = useState(initial.trust_scanner_verdict);
  const [maxFiles, setMaxFiles] = useState(String(initial.max_source_files));
  const [penalty, setPenalty] = useState(
    Object.fromEntries(SEVERITIES.map((s) => [s, String(initial.severity_rollup_penalty[s] ?? 0)])),
  );

  async function onSave() {
    setSaving(true);
    setError(null);
    const result = await createPolicyVersionFromForm(assetType, {
      block_on: blockOn,
      trust_scanner_verdict: trust,
      max_source_files: Number(maxFiles),
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
        <h3 className="eyebrow mb-1">Blocking severities</h3>
        <p className="mb-3 max-w-2xl text-[11px] leading-relaxed text-muted">
          A finding at any of these severities means the submission requires review. Everything
          else is recorded as information. This choice is the judgement call — there is no
          second decision mode on top of it.
        </p>
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
        <h3 className="eyebrow mb-1">Assessment coverage</h3>
        <p className="mb-3 max-w-2xl text-[11px] leading-relaxed text-muted">
          Source files the behavioral analyzer examines per scan. It makes one model call per
          file, so this trades coverage against wall clock. Anything beyond the cap is reported
          as a finding whose severity reflects how much went unexamined — never as a clean
          result. Submitting one server directory rather than a whole monorepo is usually
          better than raising this.
        </p>
        <label className="flex items-center gap-2 text-[12px]">
          <input
            value={maxFiles}
            onChange={(e) => setMaxFiles(e.target.value.replace(/\D/g, ""))}
            className={fieldClass("w-24")}
            aria-label="max source files"
          />
          <span className="text-muted">files per scan</span>
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
