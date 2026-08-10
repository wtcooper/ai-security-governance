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

## Second pass: multi-agent scan (`claude-security` plugin)

Run after the focused review, at high effort across the whole repository. Reported second here
because its most useful result was catching a defect in the *first* pass's remediation.

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
- **Frontend XSS** — no `dangerouslySetInnerHTML`, `innerHTML`, `srcdoc`, `eval` or
  `new Function` anywhere; scanner findings render as React text children.

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

- **The scan did not finish cleanly.** A session limit killed 12 of 34 researchers mid-run; only
  the two areas named above were re-run. `backend/app/scoring/`, `gateway/` and the deploy
  configuration were never audited, and **no secrets sweep ran** — nothing here verifies that no
  credential is committed anywhere. Sixteen further candidate sites fell below the verification
  cap and are recorded as open questions rather than findings.
- Conclusively cleared, for what it is worth: the startup DDL in `db.py` (all interpolants are
  compile-time constants from `models.py`), and frontend XSS (every submission-derived string
  lands as an escaped JSX text child, no raw-HTML sink anywhere).
- Recall is measured on one sample per MCP threat category, not all 141 servers.
- The false-positive denominators are 2 and 4. Enough to show the skill rule discriminates and
  that the MCP rule does not yet; nowhere near enough to call either rule calibrated.
- The corpora are the scanner vendor's own, so they are likely favourable to their detections.
- **No third-party penetration test, and no human security reviewer.** Both passes were run by
  Claude Code tooling against code Claude Code wrote. That is a real limitation of this evidence,
  not a formality: a reviewer sharing the author's blind spots will share its misses. Treat these
  results as a floor, not a clearance.
