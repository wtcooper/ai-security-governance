"""Measuring our own detection against the vendor eval corpora.

Both Cisco scanner repos ship labelled corpora. They live in the GitHub repos, not the PyPI
packages, so they are cloned on demand rather than vendored — vendoring third-party corpora
would go stale silently, and staleness in a calibration baseline is worse than absence.

What this measures, and what it does not:

* **Recall is well covered.** 141 labelled-malicious MCP servers across 14 threat categories,
  and 17 labelled-malicious skills. If our configured gate misses these, that is a real gap.
* **The false-positive baseline is thin.** Three benign MCP files and four safe skills. Enough
  to catch a rule that fires on everything, not enough to establish a rate you would stake an
  auto-approval on. Reported with its denominator so nobody reads more into it than it holds.

The point of running *our* pipeline rather than the vendors' runners is that we are not
grading the scanners — we are grading the whole path: our invocation, our parsing, our
severity mapping, and our policy gate. A scanner that flags something we then fail to parse
is, for governance purposes, a miss.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.models import AssetType, Decision, Severity
from app.scoring import gates
from app.scoring.policy import load_policy_dir

CORPORA = {
    "mcp": "https://github.com/cisco-ai-defense/mcp-scanner",
    "skill": "https://github.com/cisco-ai-defense/skill-scanner",
}


@dataclass
class CaseResult:
    corpus: str
    category: str
    name: str
    expected_malicious: bool
    # What our gate actually decided, which is the thing being calibrated.
    blocked: bool
    decision: str
    severities: dict[str, int] = field(default_factory=dict)
    finding_count: int = 0
    scanner_says_safe: bool | None = None
    error: str | None = None

    @property
    def outcome(self) -> str:
        """Confusion-matrix cell, from the gate's decision against the label."""
        if self.error:
            return "error"
        if self.expected_malicious:
            return "true_positive" if self.blocked else "false_negative"
        return "false_positive" if self.blocked else "true_negative"


@dataclass
class CalibrationReport:
    started_at: str
    corpus_revisions: dict[str, str]
    policy_version: str
    policy_hash: str
    scanner_model: str
    cases: list[CaseResult] = field(default_factory=list)
    # Recorded because a sampled run must never be mistaken for a full one.
    sampling: dict[str, object] = field(default_factory=dict)

    def summary(self) -> dict[str, object]:
        out: dict[str, object] = {}
        for corpus in sorted({c.corpus for c in self.cases}):
            cases = [c for c in self.cases if c.corpus == corpus]
            counts = {
                key: sum(1 for c in cases if c.outcome == key)
                for key in ("true_positive", "false_negative", "false_positive", "true_negative", "error")
            }
            malicious = counts["true_positive"] + counts["false_negative"]
            benign = counts["false_positive"] + counts["true_negative"]
            out[corpus] = {
                **counts,
                "malicious_total": malicious,
                "benign_total": benign,
                # Named "recall" only where there is a denominator to divide by.
                "recall": round(counts["true_positive"] / malicious, 4) if malicious else None,
                "false_positive_rate": (
                    round(counts["false_positive"] / benign, 4) if benign else None
                ),
                "fp_denominator_warning": (
                    f"only {benign} benign case(s): indicative, not a rate to gate on"
                    if 0 < benign < 20
                    else None
                ),
                "per_category_misses": sorted(
                    {c.category for c in cases if c.outcome == "false_negative"}
                ),
            }
        return out


async def clone_corpus(name: str, cache_dir: Path) -> tuple[Path, str]:
    """Shallow-clone (or reuse) a corpus repo and return its path and revision."""
    target = cache_dir / name
    if not (target / ".git").exists():
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", "--quiet", CORPORA[name], str(target),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"clone of {CORPORA[name]} failed: {stderr.decode()[-400:]}")

    process = await asyncio.create_subprocess_exec(
        "git", "-C", str(target), "rev-parse", "--short", "HEAD",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    return target, stdout.decode().strip() or "unknown"


def mcp_cases(repo: Path, per_category: int | None) -> list[tuple[str, str, Path, bool]]:
    """(category, name, path, expected_malicious) for the MCP corpus.

    Each malicious sample is a single .py file. They are copied into a directory per case
    before scanning, because the scanner takes a source tree.
    """
    cases: list[tuple[str, str, Path, bool]] = []
    data = repo / "evals" / "behavioral-analysis" / "data"
    for category_dir in sorted(p for p in data.iterdir() if p.is_dir()):
        files = sorted(category_dir.glob("*.py"))
        chosen = files if per_category is None else files[:per_category]
        for path in chosen:
            cases.append((category_dir.name, path.stem, path, True))

    benign = repo / "evals" / "remote" / "benign"
    if benign.is_dir():
        for path in sorted(benign.glob("*.py")):
            cases.append(("remote-benign", path.stem, path, False))
    return cases


def skill_cases(repo: Path) -> list[tuple[str, str, Path, bool]]:
    """(category, name, path, expected_malicious) for the skill corpus.

    Labels come from the corpus's own `_expected.json` (`expected_safe`) where present, and
    from the safe/malicious directory split for `test_skills`.
    """
    cases: list[tuple[str, str, Path, bool]] = []

    for expected_file in sorted(repo.glob("evals/skills/**/_expected.json")):
        skill_dir = expected_file.parent
        try:
            expected = json.loads(expected_file.read_text())
        except json.JSONDecodeError:
            continue
        cases.append(
            (
                skill_dir.parent.name,
                skill_dir.name,
                skill_dir,
                not bool(expected.get("expected_safe", False)),
            )
        )

    for label, malicious in (("safe", False), ("malicious", True)):
        root = repo / "evals" / "test_skills" / label
        if not root.is_dir():
            continue
        for skill_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            cases.append((f"test_skills-{label}", skill_dir.name, skill_dir, malicious))
    return cases


async def _scan_case(
    settings: Settings,
    corpus: str,
    category: str,
    name: str,
    path: Path,
    expected_malicious: bool,
    workspace: Path,
) -> CaseResult:
    from app.engines import mcp_scanner, skill_scanner

    policy = load_policy_dir(settings.policy_dir)
    asset_type = AssetType.MCP if corpus == "mcp" else AssetType.SKILL

    try:
        if corpus == "mcp":
            # The scanner takes a tree; a single-file sample is staged into one.
            case_dir = workspace / f"{category}--{name}"
            if case_dir.exists():
                shutil.rmtree(case_dir)
            case_dir.mkdir(parents=True)
            shutil.copy2(path, case_dir / path.name)
            result = await mcp_scanner.scan_source(settings, case_dir, timeout=900)
        else:
            result = await skill_scanner.scan_skill(settings, path, timeout=900)

        counts = result.severity_counts()
        outcome = gates.decide_scanner(
            policy,
            asset_type,
            counts,
            scanner_says_safe=result.scanner_says_safe,
            scan_failed=not result.ok,
        )
        # Advisory mode never approves, so "blocked" must mean a real blocking signal rather
        # than the mode. Otherwise every case would look like a detection.
        blocking = list(outcome.blocking_reasons)

        return CaseResult(
            corpus=corpus,
            category=category,
            name=name,
            expected_malicious=expected_malicious,
            blocked=bool(blocking),
            decision=outcome.decision.value,
            severities={k.value: v for k, v in counts.items()},
            finding_count=len(result.findings),
            scanner_says_safe=result.scanner_says_safe,
            error="; ".join(result.errors)[:400] if result.errors and not result.ok else None,
        )
    except Exception as exc:  # noqa: BLE001 - one bad case must not end the sweep
        return CaseResult(
            corpus=corpus,
            category=category,
            name=name,
            expected_malicious=expected_malicious,
            blocked=False,
            decision=Decision.ERROR.value,
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_calibration(
    settings: Settings,
    corpora: tuple[str, ...] = ("mcp", "skill"),
    mcp_per_category: int | None = 1,
    limit: int | None = None,
) -> CalibrationReport:
    """Scan the labelled corpora with our own pipeline and score ourselves against the labels.

    `mcp_per_category` samples the malicious set, because the behavioral analyzer invokes a
    model per file and the full 141 would take over an hour on a local model. None means the
    whole corpus. The sample size is recorded in the report either way.
    """
    cache = settings.workspace_dir / "corpora"
    workspace = settings.workspace_dir / "calibration"
    workspace.mkdir(parents=True, exist_ok=True)

    policy = load_policy_dir(settings.policy_dir)
    report = CalibrationReport(
        started_at=datetime.now(UTC).isoformat(),
        corpus_revisions={},
        policy_version=policy.version,
        policy_hash=policy.content_hash,
        scanner_model=settings.scanner_model,
        sampling={
            "mcp_per_category": mcp_per_category,
            "case_limit": limit,
            "note": (
                "Sampled runs measure the same pipeline as a full run but over fewer cases; "
                "recall from a sample is an estimate, not the corpus figure."
            ),
        },
    )

    all_cases: list[tuple[str, str, str, Path, bool]] = []
    for corpus in corpora:
        repo, revision = await clone_corpus(corpus, cache)
        report.corpus_revisions[corpus] = revision
        found = mcp_cases(repo, mcp_per_category) if corpus == "mcp" else skill_cases(repo)
        all_cases += [(corpus, cat, name, path, mal) for cat, name, path, mal in found]

    if limit is not None:
        all_cases = all_cases[:limit]
    report.sampling["cases_run"] = len(all_cases)

    # Progress is printed per case rather than only at the end: a sweep over a local model
    # takes a long time, and a silent run gives no way to tell slow from stuck.
    for index, (corpus, category, name, path, malicious) in enumerate(all_cases, start=1):
        result = await _scan_case(settings, corpus, category, name, path, malicious, workspace)
        report.cases.append(result)
        print(
            f"[{index}/{len(all_cases)}] {corpus}/{category}/{name}: "
            f"{result.outcome} ({result.finding_count} findings)",
            flush=True,
        )

    return report


def write_report(report: CalibrationReport, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {**asdict(report), "summary": report.summary()}
    destination.write_text(json.dumps(payload, indent=2))
    return destination


def format_summary(report: CalibrationReport) -> str:
    lines = [
        f"corpus revisions: {report.corpus_revisions}",
        f"policy v{report.policy_version} ({report.policy_hash})  "
        f"analyzer model: {report.scanner_model}",
        f"cases run: {report.sampling.get('cases_run')}  "
        f"(mcp_per_category={report.sampling.get('mcp_per_category')})",
        "",
    ]
    for corpus, stats in report.summary().items():
        recall = stats["recall"]
        fpr = stats["false_positive_rate"]
        lines.append(f"{corpus}:")
        lines.append(
            f"  malicious {stats['malicious_total']:>3}  detected {stats['true_positive']:>3}  "
            f"missed {stats['false_negative']:>3}  "
            f"recall {'n/a' if recall is None else f'{recall:.0%}'}"
        )
        lines.append(
            f"  benign    {stats['benign_total']:>3}  flagged  {stats['false_positive']:>3}  "
            f"clean  {stats['true_negative']:>3}  "
            f"FP rate {'n/a' if fpr is None else f'{fpr:.0%}'}"
        )
        if stats["fp_denominator_warning"]:
            lines.append(f"  ! {stats['fp_denominator_warning']}")
        if stats["error"]:
            lines.append(f"  ! {stats['error']} case(s) errored")
        if stats["per_category_misses"]:
            lines.append(f"  missed categories: {', '.join(stats['per_category_misses'])}")
    return "\n".join(lines)


async def _main() -> int:
    import argparse

    from app.config import get_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", action="append", choices=sorted(CORPORA), default=None)
    parser.add_argument(
        "--mcp-per-category",
        type=int,
        default=1,
        help="malicious MCP samples per threat category; 0 means the whole corpus",
    )
    parser.add_argument("--limit", type=int, default=None, help="cap total cases")
    parser.add_argument("--out", default=None, help="where to write the JSON report")
    args = parser.parse_args()

    settings = get_settings()
    report = await run_calibration(
        settings,
        corpora=tuple(args.corpus or CORPORA),
        mcp_per_category=None if args.mcp_per_category == 0 else args.mcp_per_category,
        limit=args.limit,
    )
    destination = Path(args.out) if args.out else settings.artifact_dir / "calibration.json"
    write_report(report, destination)
    print(format_summary(report))
    print(f"\nreport: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
