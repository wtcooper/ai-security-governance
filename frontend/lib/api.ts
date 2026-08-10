/**
 * Backend client.
 *
 * Server Components fetch through this, so the base URL is a server-side env var
 * (no NEXT_PUBLIC_ needed) and points at the compose service name in a container.
 */

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

export type AssetType = "llm" | "mcp" | "skill";

export type GatewayStatus = {
  ok: boolean;
  base_url: string;
  detail: string;
};

export type PreflightCheck = {
  role: string;
  model: string;
  ok: boolean;
  detail: string;
  latency_ms: number | null;
  upstream_error: string | null;
};

export type PreflightResponse = {
  ok: boolean;
  base_url: string;
  checks: PreflightCheck[];
};

export type Score = {
  check_id: string;
  metric: string;
  raw_value: number | null;
  normalized: number | null;
  direction: string | null;
  threshold: number | null;
  gated: boolean;
  passed: boolean | null;
  provenance: string;
  source_url: string | null;
  model_used: string | null;
  total_samples: number | null;
  unresolved_samples: number | null;
};

export type Finding = {
  analyzer: string;
  severity: string;
  rule_id: string | null;
  title: string;
  detail: string | null;
  file_path: string | null;
};

export type GateOutcome = {
  check_id: string;
  metric: string;
  raw_value: number | null;
  threshold: number;
  direction: string;
  passed: boolean;
  reason: string;
  description: string;
};

export type Run = {
  id: number;
  asset_id: number;
  asset_name: string;
  asset_type: AssetType;
  identifier: string;
  status: string;
  decision: string | null;
  decision_reason: string | null;
  gateway_model: string | null;
  judge_model: string | null;
  sample_override: number | null;
  judge_unresolved_rate: number | null;
  judge_refusal_rate: number | null;
  policy_version: string | null;
  policy_hash: string | null;
  engine_version: string | null;
  ruleset_version: string | null;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  composite_score: number | null;
  composite_is_display_only: boolean;
  scores: Score[];
  findings: Finding[];
  gate_outcomes: GateOutcome[];
  artifacts: string[];
};

export type EvaluationGate = {
  check_id: string;
  metric: string;
  raw_value: number | null;
  threshold: number | null;
  direction: string | null;
  passed: boolean | null;
  provenance: string;
  total_samples: number | null;
};

export type EvaluationRow = {
  run_id: number;
  asset_name: string;
  asset_type: AssetType;
  identifier: string;
  status: string;
  decision: string | null;
  decision_reason: string | null;
  composite_score: number | null;
  composite_is_display_only: boolean;
  judge_model: string | null;
  judge_unresolved_rate: number | null;
  judge_refusal_rate: number | null;
  policy_version: string | null;
  gates_passed: number;
  gates_total: number;
  samples_min: number | null;
  samples_max: number | null;
  sample_override: number | null;
  started_at: string;
  finished_at: string | null;
  gates: EvaluationGate[];
};

export type CheckInfo = {
  id: string;
  metric: string;
  direction: string;
  needs_judge: boolean;
  description: string;
  planned_samples: number;
  uses_core_set: boolean;
  threshold: number | null;
};

export type PolicyView = {
  classes: Record<string, { version: string; content_hash: string }>;
  judge: { default_model: string; max_refusal_rate: number };
  default_subject_model: string;
  scanner_model: string;
  llm_gates: Record<
    string,
    {
      metric: string;
      direction: string;
      threshold: number;
      samples: number;
      sample_ids_count: number;
      uses_core_set: boolean;
      planned_samples: number;
      description: string;
    }
  >;
  composite_weights: Record<string, number>;
  composite_is_display_only: boolean;
  scanner: Record<
    string,
    { block_on: string[]; trust_scanner_verdict: boolean; max_source_files: number }
  >;
  thresholds_are_calibrated: boolean;
  calibration_note: string;
};

export type PolicyVersionMeta = {
  asset_type: AssetType;
  version: number;
  content_hash: string;
  note: string | null;
  created_at: string;
  is_active: boolean;
};

export type PolicyVersionOut = PolicyVersionMeta & { content: string };

/** Form-shaped view of the active policy's key settings. */
export type LlmGateFormValues = {
  enabled: boolean;
  metric: string;
  direction: string;
  threshold: number;
  samples: number;
  sample_ids_count: number;
  weight: number;
  description: string;
  needs_judge: boolean;
  dataset_max: number;
  calls_per_sample: number;
};

export type DepthPreset = {
  key: string;
  label: string;
  blurb: string;
  /** null means "the whole dataset". */
  samples: number | null;
  per_check: Record<string, number>;
  total_tests: number;
  total_calls: number;
};

export type LlmFormValues = {
  judge_default_model: string;
  judge_max_refusal_rate: number;
  depth_presets: DepthPreset[];
  /** Every REGISTERED benchmark, enabled or not, so the form can offer additions. */
  gates: Record<string, LlmGateFormValues>;
  weights_block_on_unsafe_file: boolean;
  weights_treat_unscanned_as_pass: boolean;
};

export type ScannerFormValues = {
  block_on: string[];
  trust_scanner_verdict: boolean;
  max_source_files: number;
  severity_rollup_penalty: Record<string, number>;
};

export type PolicyFormOut =
  | { asset_type: "llm"; version: number; values: LlmFormValues }
  | { asset_type: "mcp" | "skill"; version: number; values: ScannerFormValues };

export type LlmFormPayload = {
  judge_default_model: string;
  judge_max_refusal_rate: number;
  gates: Record<
    string,
    {
      enabled: boolean;
      threshold: number;
      samples: number;
      weight: number;
      clear_sample_ids: boolean;
    }
  >;
  weights_block_on_unsafe_file: boolean;
  weights_treat_unscanned_as_pass: boolean;
  note: string;
};

export type ScannerFormPayload = ScannerFormValues & { note: string };

export type BenchmarkGateInfo = {
  threshold: number;
  samples: number;
  sample_ids_count: number;
  uses_core_set: boolean;
} | null;

export type BenchmarkInfo = {
  id: string;
  description: string;
  intent: string;
  metric: string;
  direction: string;
  needs_judge: boolean;
  strata_key: string | null;
  gate: BenchmarkGateInfo;
  composite_weight: number | null;
  dataset_total: number | null;
  preview_available: boolean;
  enabled: boolean;
  calls_per_sample: number;
  dataset_size: number | null;
  cost_note: string;
  needs_sandbox: boolean;
  estimated_calls: number | null;
};

export type BenchmarkPreview = {
  built_at: string;
  total_samples: number;
  strata_key: string | null;
  strata: Record<string, number>;
  metadata_keys: string[];
  examples: {
    id: string;
    input: string;
    target: string;
    metadata: Record<string, string>;
  }[];
};

export type BenchmarkDetail = BenchmarkInfo & {
  preview: BenchmarkPreview | null;
  active_sample_ids: string[];
};

export type CoreSetProposal = {
  check_id: string;
  size: number;
  seed: string;
  sample_ids: string[];
  allocation: Record<string, { selected: number; available: number }>;
  yaml_snippet: string;
};

export type RunProgress = {
  status: string;
  sample_override: number | null;
  benchmarks: {
    check_id: string;
    state: "done" | "running" | "queued";
    samples_completed: number | null;
    samples_planned: number | null;
  }[];
};

/** Never cache: these endpoints describe live infrastructure and run state. */
async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${path} returned HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

/**
 * Infrastructure reads return null instead of throwing: a page must still render (and say
 * what is wrong) when the gateway or backend is down.
 */
async function getJsonOrNull<T>(path: string): Promise<T | null> {
  try {
    return await getJson<T>(path);
  } catch {
    return null;
  }
}

export const fetchGatewayStatus = () => getJsonOrNull<GatewayStatus>("/api/gateway/status");
export const fetchModels = () => getJsonOrNull<string[]>("/api/models");
export const fetchChecks = (assetType: AssetType) =>
  getJsonOrNull<CheckInfo[]>(`/api/checks?asset_type=${assetType}`);
export const fetchPolicy = () => getJsonOrNull<PolicyView>("/api/policy");
export const fetchEvaluations = (assetType: AssetType) =>
  getJsonOrNull<EvaluationRow[]>(`/api/evaluations/${assetType}`);
export const fetchRun = (runId: string) => getJsonOrNull<Run>(`/api/runs/${runId}`);
export const fetchRunProgress = (runId: number) =>
  getJsonOrNull<RunProgress>(`/api/runs/${runId}/progress`);
export const fetchPolicyVersions = (assetType: AssetType) =>
  getJsonOrNull<PolicyVersionMeta[]>(`/api/policies/${assetType}/versions`);
export const fetchPolicyVersion = (assetType: AssetType, version: number) =>
  getJsonOrNull<PolicyVersionOut>(`/api/policies/${assetType}/versions/${version}`);
export type BenchmarkSuite = {
  benchmarks: BenchmarkInfo[];
  suite: {
    enabled_count: number;
    available_count: number;
    estimated_calls: number;
    judged_count: number;
  };
};

export const fetchBenchmarks = () => getJsonOrNull<BenchmarkSuite>("/api/benchmarks");
export const fetchBenchmark = (checkId: string) =>
  getJsonOrNull<BenchmarkDetail>(`/api/benchmarks/${checkId}`);

async function postJson<T>(
  path: string,
  body: unknown,
): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const text = await response.text();
  if (!response.ok) {
    let detail = text;
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
    } catch {
      /* keep the raw body */
    }
    return { ok: false, error: detail };
  }
  return { ok: true, data: JSON.parse(text) as T };
}

export const createPolicyVersion = (
  assetType: AssetType,
  content: string,
  note: string,
): Promise<{ ok: true; data: PolicyVersionOut } | { ok: false; error: string }> =>
  postJson<PolicyVersionOut>(`/api/policies/${assetType}/versions`, { content, note });

export const fetchPolicyForm = (assetType: AssetType, version?: number) =>
  getJsonOrNull<PolicyFormOut>(
    `/api/policies/${assetType}/form${version != null ? `?version=${version}` : ""}`,
  );

export const createPolicyVersionFromForm = (
  assetType: AssetType,
  payload: LlmFormPayload | ScannerFormPayload,
): Promise<{ ok: true; data: PolicyVersionOut } | { ok: false; error: string }> =>
  postJson<PolicyVersionOut>(`/api/policies/${assetType}/form`, payload);

export const buildBenchmarkPreview = (
  checkId: string,
): Promise<{ ok: true; data: BenchmarkDetail } | { ok: false; error: string }> =>
  postJson<BenchmarkDetail>(`/api/benchmarks/${checkId}/preview`, undefined);

export const proposeCoreSet = (
  checkId: string,
  size: number,
  seed: string,
): Promise<{ ok: true; data: CoreSetProposal } | { ok: false; error: string }> =>
  postJson<CoreSetProposal>(`/api/benchmarks/${checkId}/core-set`, { size, seed });

export type UploadResult = {
  identifier: string;
  filename: string;
  size_bytes: number;
  entry_count: number;
  source_file_count: number;
  max_source_files: number;
  exceeds_coverage: boolean;
};

/** Upload a zip of an MCP server or skill; the returned identifier starts a run. */
export async function uploadArchive(
  file: File,
  assetType: "mcp" | "skill",
): Promise<{ ok: true; upload: UploadResult } | { ok: false; error: string }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/api/uploads?asset_type=${assetType}`, {
    method: "POST",
    body: form,
    cache: "no-store",
  });
  const text = await response.text();
  if (!response.ok) {
    let detail = text;
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
    } catch {
      /* keep the raw body */
    }
    return { ok: false, error: detail };
  }
  return { ok: true, upload: JSON.parse(text) as UploadResult };
}

export async function createRun(body: {
  asset_type: AssetType;
  name: string;
  identifier: string;
  judge_model?: string;
  limit?: number;
}): Promise<{ ok: true; run: Run } | { ok: false; error: string }> {
  const response = await fetch(`${API_BASE}/api/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
    } catch {
      /* keep the raw body: a gateway error body is the useful diagnostic */
    }
    return { ok: false, error: detail };
  }
  return { ok: true, run: (await response.json()) as Run };
}
