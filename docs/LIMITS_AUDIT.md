# Audit of every limit, cap, timeout and truncation

Prompted by a fair challenge: the MCP behavioral scan was capped at **40 source files**, a
number nobody chose deliberately — it was whatever ran fast enough during development, and it
silently under-scanned every real repository. This is a sweep of every other numeric constant
in the codebase, with a verdict on each.

The classification that matters is not "big or small" but **what happens when the limit
bites**:

- **Fails closed** — the run becomes an error or a finding. Safe: a reviewer sees it.
- **Fails open** — the run still produces a verdict over less evidence. Dangerous: an
  under-assessed asset reads like a clean one.
- **Cosmetic** — display only; the underlying record is intact.

Every fail-open limit found in this audit has been fixed.

## Fixed: limits that reduced assessment coverage

| Limit | Was | Now | Why it mattered |
|---|---|---|---|
| MCP behavioral file cap | **40**, hard-coded | **`max_source_files: 200`** in the mcp/skill policy, editable in the UI | Fail-open. On a 106-file monorepo it scanned 40 and reported no findings. The trade-off is real, so it is now governed, versioned and visible rather than a constant. |
| Capped-scan file *selection* | first 40 **alphabetically** | ranked by MCP relevance | Fail-open, and worse than the cap itself: alphabetical order kept `.agents/` and `docs/` and dropped `packages/mcp/src/index.ts`, the only file defining tools. |
| Coverage-shortfall severity | flat **MEDIUM** | **HIGH ≥50% missed, MEDIUM ≥20%, LOW** below | Missing 62% of a tree was reported at the same severity as missing 5%. |
| `SKIP_DIRS` | included **`tests`** | removed | Fail-open. An entire directory class of submitted code was invisible. Relevance ranking already sorts tests to the back of a capped scan, so excluding them bought nothing. |
| `SOURCE_SUFFIXES` | **7** (Python + JS/TS only) | **27** (adds Go, Rust, Ruby, Java, C#, C/C++, shell, Lua, Perl, Swift, Kotlin) | Fail-open. An MCP server written in Go had *no* selectable source files. |
| Findings detail shown | truncated at **400** chars | 1,500 with an explicit pointer to the artifact | Cosmetic but real: threat summaries were cut mid-sentence, hiding the reasoning behind a finding. |
| List endpoint page size | runs **50**, evaluations **100** | **500** both | Fail-open at the margin: older runs vanished from a list with no indication. |

## Keep: security limits

These exist to stop a hostile submission consuming the host, and they all fail closed.

| Limit | Value | Behaviour when hit |
|---|---|---|
| `MAX_ARCHIVE_BYTES` | 100 MB compressed | upload rejected |
| `MAX_UNCOMPRESSED_BYTES` | 500 MB expanded | rejected — zip-bomb guard, checked before extraction |
| `MAX_MEMBERS` | 20,000 entries | rejected |
| `MAX_REDIRECTS` (published-score fetch) | 3 | error — each hop re-validated against the SSRF guard |
| `MAX_BYTES` (published-score fetch) | 5 MB | response truncated; it is parsed for candidate scores a human then confirms |
| Single-root strip depth | 8 levels | stops descending; pathological nesting cannot loop |
| `_SCORE_READ_BYTES` | 64 KB per file | ranking heuristic only — never limits what gets *scanned* |

## Keep: timeouts

All verified to **fail closed**. A scanner timeout returns exit 124, which yields no JSON,
which sets `ok=False` and resolves the run to ERROR. A clone timeout raises. None can produce
an approval.

| Operation | Timeout |
|---|---|
| Benchmark eval (per benchmark) | 3,600 s |
| Scanner sweep | 1,800 s |
| Benchmark dataset preview build | 600 s |
| Git clone | 300 s |
| Published-score page fetch | 600 s |
| Hugging Face scan harvest | 60 s |
| Gateway preflight / model list | 15 s / 10 s |

## Keep: display truncation

The stored record is always complete; these bound what a page renders. The scanner artifact
holds the raw output in full.

| Truncation | Value |
|---|---|
| Finding `detail` stored | 4,000 chars |
| Error and stderr tails | 400–2,000 chars |
| Dataset preview examples | 6 samples; input 600, target 300, metadata 200 chars |
| Unsafe weight files named in a decision reason | first 5 |
| Policy content hash | 16 hex chars |

## Keep, but worth knowing

| Behaviour | Value | Note |
|---|---|---|
| Run concurrency | **1** | Runs are serialised deliberately: a local Ollama box serving several evals at once makes all of them slower without finishing any sooner. A second submission queues rather than failing. |
| Dependency manifest staged | **first match per filename** | The dependency analyzer takes a single manifest path, so a monorepo's other manifests are not audited. Submit the individual server to get its own dependencies assessed. |
| `Check.default_limit` | 20 | Effectively dead for execution: only policy-gated benchmarks run, and the policy always supplies a sample count. It survives as a display fallback. |
| Core-set proposal size | ≤ 5,000 | An API bound on a request parameter, not a cap on anything measured. |

## The invariant this audit establishes

Tests now assert the properties rather than the numbers, so the same drift cannot recur
silently: `test_the_file_cap_comes_from_policy_and_covers_a_normal_submission`,
`test_no_whole_directory_class_is_silently_excluded_from_scanning`,
`test_source_selection_covers_more_than_two_languages`,
`test_coverage_shortfall_severity_scales_with_how_much_was_missed`, and
`test_the_file_cap_prioritises_files_that_define_mcp_tools`.

The rule going forward: **a limit that reduces what gets assessed belongs in the policy, not in
the code.** A limit that protects the host belongs in the code, and must fail closed.
