# Security testing of this tool

A tool that evaluates the security of other people's code should be able to show its own
results. Everything below was run against this repository.

## What was used

| Tool | What it is | How it was used here |
|---|---|---|
| **Claude Code's `security-review` skill** | The built-in focused security review. Analyses a change set for high-confidence, exploitable findings, with a false-positive filter pass that discards anything below high confidence. | The first pass, over the Phase 3–5 commit. It found the SSRF and path-containment issues. |
| **The `claude-security` plugin** | A multi-agent scan orchestrator. Partitions the repository into components, dispatches researcher agents per component, then puts every candidate finding to an independent verifier panel before it is reported. | The second pass, at high effort over the whole repository, findings-only (no patches). It found that one of the first pass's own *fixes* was broken. |

Both are Claude Code tooling, so this is genuinely dogfooding: the same assistant that wrote
the code reviewed it, which is worth weighing when reading the results — see
[what this does not establish](#what-this-does-not-establish).

## Third pass: complete multi-agent scan (2026-08-10)

Run again with the `claude-security` plugin, at high effort across the whole repository (117
tracked files, up from 86 at the second pass below). Unlike that earlier run — which lost 12 of
34 researchers to a session limit — every one of the 74 dispatched researchers returned this
time, so this is the first pass with full coverage: all five top-level directories accounted for
as scanned or explicitly skipped (vendored dependencies and caches only), no directory left out
for lack of time.

**Six findings survived verification: zero HIGH, four MEDIUM, two LOW.** Two are fixed, two are
still open, and two could not be patched — status per finding below. Full detail, including the
ones that didn't survive the panel, is in
[`docs/security/2026-08-10-full-scan/CLAUDE-SECURITY-RESULTS.md`](security/2026-08-10-full-scan/CLAUDE-SECURITY-RESULTS.md).

- ✅ **A published score's `source_url` rendered as a live link with no scheme allowlist**
  (MEDIUM, 3/3 panel; plus a LOW open-redirect variant on the same sink, closed by the same fix).
  A `javascript:` URI reaching this field executed in the app's origin when a reviewer clicked
  "source". **Fixed:** an `httpUrl()` guard parses the value with the WHATWG `URL` parser and
  emits an `href` only for `http:`/`https:`, rendering anything else as escaped text. Probed
  against `javascript:`, `JavaScript:`, leading-whitespace, `java\tscript:`, `data:`, `vbscript:`
  and NUL-prefixed variants. An independent reviewer of the diff alone found no new attack path.

- ✅ **A TOCTOU race in policy version numbering** (LOW, 3/3 panel). `create_version` read the
  highest version then inserted `current + 1` with no row lock and no unique constraint, so
  concurrent writes could leave two rows claiming the same version. **Fixed:** a unique index on
  `(asset_type, version)`, a startup pass that adds it to databases that already exist, and a
  bounded retry so a race loser takes the next free number. An 8/16/32-thread stress produced
  duplicates before the fix and none after.

- ⬜ **The policy-versioning endpoint has no authentication** (MEDIUM, 2/3 panel). `POST
  /api/policies/{asset_type}/versions` accepts writes from anything that can reach the backend —
  no API key, no session, no CSRF token. `gates.py` trusts the newest policy version for every
  future approve/deny decision, so this is a way to silently relax or disable the tool's own
  governance thresholds. **Open — and this one needs a product decision, not a patch:** the app
  has no authentication anywhere, and the browser client has no way to hold a credential, so any
  mandatory token would break the shipped frontend. See "What this does not establish".

- ⬜ **The benchmark-score extraction prompt concatenates fetched page text with no delimiting**
  (MEDIUM, 3/3 panel). `POST /api/published-scores/extract` feeds a fetched page's raw text
  straight into the LLM instruction prompt, so a page can embed hidden instructions that
  fabricate a passing benchmark score for an inattentive reviewer to approve. **A fix is written
  and passed independent verification (251 tests), but its adversarial review did not complete —
  so it is deliberately not applied.** It is held at
  `CLAUDE-SECURITY-20260810-151644/.claude-security-run/patch-20260810-170834/F4.diff`.

- ⛔ **The MCP/skill upload endpoint accepts unauthenticated, non-preflighted requests from any
  origin** (MEDIUM, 2/3 panel). `uploadArchive` posts `multipart/form-data` with no custom
  headers, which browsers never preflight — any page the operator's browser visits while the
  stack is up can silently trigger an upload-and-scan job on the local backend. **Could not be
  patched at the time:** its file, `frontend/lib/api.ts`, was excluded from version control (see
  below), so no patch could be built against the committed tree. That exclusion is now fixed, so
  this finding is patchable from here on.

### The scan also exposed a repository-integrity bug

Not a vulnerability, but more immediately damaging than most of the above: the root `.gitignore`
carried the stock Python packaging pattern `lib/`, **unanchored**, so it also matched
`frontend/lib/`. That directory had **never been committed**, while 17 tracked frontend files
import from it — a fresh clone produced a frontend that could not build. The pattern is now
anchored to `/lib/` and `frontend/lib/api.ts` is tracked. It surfaced only because a patch
attempt tried to edit a file that turned out not to exist in the repository.

This run read every tracked file — tests and fixtures included, no `focus` filter applied — so it
closes the second pass's "no secrets sweep ran" gap for the current tree, though no *dedicated*
secrets category was named separately in this run's coverage record.

## Second pass: multi-agent scan (`claude-security` plugin, 2026-08-08)

Run after the focused review, at high effort across the whole repository. Reported here because
its most useful result was catching a defect in the *first* pass's remediation. (Superseded for
coverage purposes by the complete third pass above — this run is kept for the fixes it drove.)

**Eight findings survived verification: four HIGH, three MEDIUM, one LOW.** The ones worth
knowing about:

- **`--recurse-submodules=no` did the opposite of its intent** (HIGH). git documents the flag as
  `--[no-]recurse-submodules[=<pathspec>]`, so the `=` form takes a *pathspec* — passing `=no`
  **enabled** submodule cloning and matched submodules at path `no`. A submitted repo could then
  have an arbitrary URL fetched from `.gitmodules`, bypassing the four-forge allowlist entirely.
  The regression test that should have caught this asserted the flag *string* appeared in the
  source, which is exactly why it passed while the flag misbehaved. It now asserts the quoted
  argv token and that the pathspec form is absent.

- **Scanner output parsing could be manipulated by the submission** (HIGH). Both `_extract_json`
  implementations counted braces without honouring JSON string quoting, and both scanners echo
  submission-controlled text into their reports — a filename for the MCP path, a source line for
  the skill path. A `}` inside that text ended the object early, so a submission could reduce or
  void its own findings while the run recorded as a clean success. Replaced with `raw_decode`,
  which is string-aware.

- **pip-audit could be pointed at a project rather than a requirements file** (contested). A
  submission can contain a *directory* named `requirements.txt`, or a `pyproject.toml`, either of
  which selects pip-audit's project mode — resolving and installing declared dependencies, i.e.
  running a build backend on attacker input. Two verifiers rated it exploitable, one refuted it on
  an argparse detail. The missing type check was certain either way, so the input is now narrowed
  to regular `requirements.txt` files only. Writing the test for this exposed that the first fix
  was incomplete: skipping the directory still left a real `pyproject.toml` *inside* it reachable.

- **The gateway image baked a default bearer token** while compose published every service on all
  interfaces. The default is gone and all published ports are now bound to `127.0.0.1`, which is
  where a single-user local tool with no authentication belongs.

On the two fixes the scan was explicitly asked to attack rather than accept: **the SSRF pinning
held and the symlink containment held**, three verifiers each. But the SSRF rewrite had *narrowed*
its own predicate — moving to `is_global` silently dropped the `is_multicast` and `is_reserved`
checks the previous version had, and admitted NAT64. No route existed (the compose network is
IPv4-only, and the https-only rule blocks the plain-HTTP internal services), but a fix should not
quietly reduce coverage, so those predicates are restored and NAT64 prefixes are now denied
explicitly.

## First pass: focused review (`security-review` skill)

Found **two MEDIUM issues, both real, both since fixed** with regression tests. Both were containment failures rather than crashes, which is the
class that matters here: this tool deliberately clones untrusted repositories and unzips
untrusted archives, so the property under test is that a submission cannot reach beyond itself.

**1. Symlink escape from a cloned repository.** `git clone` checked out symlinks, and the scan
path then followed them: the file walk used `is_file()` (which follows a link) with the suffix
taken from the *link* name, and the bounded-scan staging step used `shutil.copy2`, which
dereferences by default. That last step copied the target's bytes into a fresh scan root as an
ordinary file — laundering external content past `mcp-scanner`'s own symlink guard, which only
rejects things still shaped like symlinks. Reproduced with a submission of 41 filler files plus
`0leak.py -> outside.env`; the linked file's contents landed in the run workspace. Fixed with
`-c core.symlinks=false` on clone, symlink and resolve-inside-root checks in the walk, and
`follow_symlinks=False` when staging. The zip path already refused symlink members; the clone
path is now consistent with it.

**2. SSRF guard weaknesses.** Two separate problems. The guard resolved the hostname and checked
every address, then handed the URL *string* to the HTTP client, which resolved again — two
lookups, so a name whose records changed in between was fetched having never been validated. And
the address filter (`is_private`, `is_loopback`, `is_link_local`, …) is not equivalent to
"globally routable": `100.64.0.1` in carrier-grade NAT space passed. Fixed by connecting to the
validated literal address with `Host` and SNI preserved, and by checking `is_global` plus an
explicit deny for `192.88.99.0/24` and `2002::/16` — the 6to4 relay prefixes, which report
`is_global == True`.

One further item was fixed as hardening rather than a finding: the scanner subprocesses received
the whole environment while eval subprocesses were scrubbed. No egress path existed (the backend
container is never given provider keys), but the asymmetry is how a leak appears after a config
change.

## Checked and cleared

Recorded because what was examined and found safe is as informative as what was flagged:

- **Zip-slip and zip symlink members** — absolute paths and any `..` component rejected before
  extraction; symlink members refused outright.
- **Submission-path allowlist** — `realpath` applied before a component-wise ancestor test, so
  `…/uploads-evil` and `…/uploads/../../etc/passwd` both fail, as do case-variant paths.
- **Upload filename handling** — the write path comes from a server-side counter; the client
  filename is used only for the extension check.
- **Command and argument injection** — all five subprocess call sites use argument lists, never a
  shell. Submission-derived paths are absolute and server-rooted, and model aliases are wrapped
  into `openai-api/gateway/<alias>`, so neither can be parsed as a flag.
- **SSRF via IP encodings** — decimal, octal, short-form and IPv4-mapped IPv6 forms are
  normalised by resolution before the check and blocked. NAT64 prefixes are denied explicitly
  rather than by normalisation, which an earlier version of this list described incorrectly.
- **Redirect handling** — redirects are followed manually with each hop re-validated, so an
  allowed host cannot bounce the fetch to a forbidden one.
- **`hf_repo_id` interpolation** — reaches only the path of a URL whose scheme and host are
  fixed literals; no payload moves the request off the host.
- **Credentials in responses** — no path was found by which a provider key reaches a response
  body, a log line, or an artifact.
- **Gate-logic bypass** — the gate reads only gated scores, compares raw values against raw
  thresholds, treats a missing score or unreliable judge or failed scan as blocking, and never
  reads the composite.
- **Executing submitted code** — the dependency audit runs with `--no-deps --disable-pip` on a
  requirements *file*, so no build backend runs; clones use `--recurse-submodules=no` and
  `core.hooksPath=/dev/null`. Nothing from a submission executes.
- **Frontend XSS via raw-HTML sinks** — no `dangerouslySetInnerHTML`, `innerHTML`, `srcdoc`,
  `eval` or `new Function` anywhere; scanner findings render as React text children. (A narrower
  exception surfaced in the third pass: a backend-supplied URL rendered into a raw `<a href>` with
  no scheme allowlist — see above.)

## Detection calibration

`scripts/calibrate.sh` runs the pipeline over the labelled corpora the Cisco scanner repos ship
and scores it against their ground truth. Analyzer model `gemma4` running locally, policy v1,
**$0 spend**:

| Corpus | Malicious | Detected | Recall | Benign | Flagged | FP rate |
|---|---|---|---|---|---|---|
| MCP servers | 14 | 12 | **86%** | 2 | 1 | **50%** ⚠️ |
| Agent skills | 17 | 15 | **88%** | 4 | 0 | **0%** |

Missed: `injection-attacks`, `template-injection` (MCP); `sql-injection`,
`test_skills-malicious` (skills). All four produced zero findings rather than findings we
mis-scored. The EICAR miss is explainable — it is an antivirus test file, and the VirusTotal
analyzer is off by default.

**The most useful result is the worst one.** A legitimate benign MCP server
(`evals/remote/benign/GitHub_tools`) was flagged HIGH — 1 of the 2 benign MCP servers that
produced a result. That is direct evidence the MCP severity rule is not yet well calibrated —
one benign server in four being flagged is a high false-positive rate. The skill rule looks
better: all four safe
skills produced zero findings.

A third benign MCP server (`azure_tools`) **timed out at 900s**, which is the scan-time
limitation below, measured rather than asserted.

The skill corpus was run twice, independently, and produced **identical per-case outcomes** —
same 15 detections, same 2 misses. Worth checking rather than assuming, because the LLM analyzer
is a model and the judge-refusal rate elsewhere in this project does vary run to run. Both
reports are committed under `data/calibration/`.

## What this does not establish

- **The second pass (2026-08-08) did not finish cleanly.** A session limit killed 12 of 34
  researchers mid-run; only the two areas named above were re-run. `backend/app/scoring/`,
  `gateway/` and the deploy configuration were never audited, and no secrets sweep ran. Sixteen
  further candidate sites fell below the verification cap and were recorded as open questions
  rather than findings. The third pass (2026-08-10) closed the coverage gap — all 74 researchers
  returned and every top-level directory was accounted for — but its own 44 verified candidates
  are a smaller pool than the second pass's 28; the two runs are not directly comparable in scope
  covered per candidate.
- **Four of the third pass's six findings are still open.** Two are fixed (the `source_url`
  render sink and the policy-version race, both with regression tests). Of the rest: the
  extraction-prompt fix is written and independently verified but its adversarial review was cut
  short by a session limit, so it is deliberately **not** applied — a fix that has not survived
  the full panel is not a fix this project will claim. The upload-CSRF finding was unpatchable
  while its file sat outside version control. And the missing-authentication finding is a design
  question: this is a single-user local tool with no auth anywhere and a browser client that
  cannot hold a credential, so closing it properly means deciding what the deployment model
  actually is — loopback-only-and-accept-it, a local token plus a client that can send it, or a
  real session layer. That decision has not been made, and a patch would be pretending otherwise.
- The third pass also ran at `high`, not `max`, so no adversarial red-team re-panel of marginal
  findings occurred, and no dedicated secrets-category pass was named (though every file was read).
- **The fixes were verified by agents, not by a human or a pen test.** Each applied fix was
  reviewed by an independent verifier that ran the project's suite, and the `source_url` fix was
  additionally challenged by a fresh reviewer given only the diff. That panel caught two real
  defects in its own proposed fixes — an unhandled 500 on an unauthenticated endpoint, and a
  fail-closed startup check that would have permanently bricked boot on any database holding
  pre-existing duplicate rows. That is the process working, but it is still Claude Code checking
  Claude Code.
- Conclusively cleared, for what it is worth: the startup DDL in `db.py` (all interpolants are
  compile-time constants from `models.py`), and raw-HTML-sink XSS (every submission-derived
  string lands as an escaped JSX text child, no raw-HTML sink anywhere) — but not the `href`-based
  variant the third pass found; see above.
- Recall is measured on one sample per MCP threat category, not all 141 servers.
- The false-positive denominators are 2 and 4. Enough to show the skill rule discriminates and
  that the MCP rule does not yet; nowhere near enough to call either rule calibrated.
- The corpora are the scanner vendor's own, so they are likely favourable to their detections.
- **No third-party penetration test, and no human security reviewer.** All three passes were run
  by Claude Code tooling against code Claude Code wrote. That is a real limitation of this evidence,
  not a formality: a reviewer sharing the author's blind spots will share its misses. Treat these
  results as a floor, not a clearance.
