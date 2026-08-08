"""Harvesting open-weight supply-chain scan results from Hugging Face.

This is the clearest win for "harvest before compute". The Hub already runs five independent
scanners over every public model file and serves the results unauthenticated:

    GET /api/models/{repo_id}/tree/{revision}?expand=true&recursive=true
      -> per file: securityFileStatus { status, protectAiScan, avScan, pickleImportScan,
                                        virusTotalScan, jFrogScan }

    GET /api/models/{repo_id}/scan
      -> { scansDone: bool, filesWithIssues: [...] }

Reproducing that locally would mean downloading tens of gigabytes of weights to re-run
scanners someone else already ran. So we read it, store the raw JSON as an artifact, and only
fall back to a local scanner when the Hub has nothing.

The one rule that matters: **`scansDone: false` is not "safe"**. An unscanned repo has no
evidence either way, and treating absence of findings as absence of risk is how a supply-chain
compromise gets auto-approved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

HF_API = "https://huggingface.co/api"

# The five scanners the Hub exposes per file. Names are the literal JSON keys.
SCANNER_KEYS = (
    "protectAiScan",
    "avScan",
    "pickleImportScan",
    "virusTotalScan",
    "jFrogScan",
)

# Weight/serialisation formats worth reporting on. Config and tokenizer files are scanned too
# but are not where deserialisation payloads live, so listing them all would bury the signal.
WEIGHT_SUFFIXES = (
    ".bin",
    ".safetensors",
    ".pt",
    ".pth",
    ".ckpt",
    ".h5",
    ".pb",
    ".onnx",
    ".msgpack",
    ".gguf",
    ".tflite",
    ".pkl",
    ".joblib",
    ".npy",
    ".npz",
)


@dataclass
class ScannerVerdict:
    scanner: str
    status: str  # "safe" | "unsafe" | "unscanned" | "queued" | ...
    message: str | None = None
    report_link: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_unsafe(self) -> bool:
        return self.status == "unsafe"

    @property
    def is_scanned(self) -> bool:
        return self.status not in ("unscanned", "queued", "")


@dataclass
class FileScan:
    path: str
    status: str
    size: int | None
    verdicts: list[ScannerVerdict]

    @property
    def is_unsafe(self) -> bool:
        return self.status == "unsafe" or any(v.is_unsafe for v in self.verdicts)

    @property
    def scanned_by(self) -> list[str]:
        return [v.scanner for v in self.verdicts if v.is_scanned]


@dataclass
class HarvestResult:
    repo_id: str
    revision: str | None
    found: bool
    scans_done: bool
    files: list[FileScan]
    files_with_issues: list[str]
    error: str | None = None
    # Raw API payloads, stored as a run artifact so a decision can be re-audited later.
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def unsafe_files(self) -> list[str]:
        return [f.path for f in self.files if f.is_unsafe]

    @property
    def weight_files(self) -> list[FileScan]:
        return [f for f in self.files if f.path.lower().endswith(WEIGHT_SUFFIXES)]

    @property
    def scanner_coverage(self) -> dict[str, int]:
        """How many files each scanner actually looked at.

        Surfaced because "five scanners" means little if four of them skipped everything.
        """
        coverage: dict[str, int] = {}
        for file in self.files:
            for scanner in file.scanned_by:
                coverage[scanner] = coverage.get(scanner, 0) + 1
        return coverage


def parse_security_status(path: str, size: int | None, payload: dict[str, Any]) -> FileScan:
    verdicts: list[ScannerVerdict] = []
    for key in SCANNER_KEYS:
        entry = payload.get(key)
        if not isinstance(entry, dict):
            continue
        verdicts.append(
            ScannerVerdict(
                scanner=key,
                status=str(entry.get("status", "unscanned")),
                message=entry.get("message"),
                report_link=entry.get("reportLink"),
                # pickleImportScan carries the actual imports, which is the useful detail
                # when a file is flagged.
                details={
                    k: v
                    for k, v in entry.items()
                    if k not in ("status", "message", "reportLink")
                },
            )
        )
    return FileScan(
        path=path,
        status=str(payload.get("status", "unscanned")),
        size=size,
        verdicts=verdicts,
    )


async def harvest(repo_id: str, revision: str = "main", token: str | None = None) -> HarvestResult:
    """Fetch Hub scan results for a model repo."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        try:
            tree_response = await client.get(
                f"{HF_API}/models/{repo_id}/tree/{revision}",
                params={"expand": "true", "recursive": "true"},
            )
            scan_response = await client.get(f"{HF_API}/models/{repo_id}/scan")
        except httpx.HTTPError as exc:
            return HarvestResult(
                repo_id=repo_id,
                revision=revision,
                found=False,
                scans_done=False,
                files=[],
                files_with_issues=[],
                error=f"{type(exc).__name__}: {exc}",
            )

    if tree_response.status_code == 404:
        return HarvestResult(
            repo_id=repo_id,
            revision=revision,
            found=False,
            scans_done=False,
            files=[],
            files_with_issues=[],
            error=f"repo {repo_id!r} not found on the Hub at revision {revision!r}",
        )
    if not tree_response.is_success:
        # Gated and private repos land here. Reported rather than swallowed, because the
        # fallback (a local scan) is a materially different and much more expensive path.
        return HarvestResult(
            repo_id=repo_id,
            revision=revision,
            found=False,
            scans_done=False,
            files=[],
            files_with_issues=[],
            error=(
                f"HTTP {tree_response.status_code} listing {repo_id!r}: "
                f"{tree_response.text[:300]}"
            ),
        )

    tree = tree_response.json()
    files = [
        parse_security_status(
            entry.get("path", "?"), entry.get("size"), entry["securityFileStatus"]
        )
        for entry in tree
        if entry.get("type") == "file" and isinstance(entry.get("securityFileStatus"), dict)
    ]

    scan_payload: dict[str, Any] = {}
    if scan_response.is_success:
        try:
            scan_payload = scan_response.json()
        except ValueError:
            scan_payload = {}

    return HarvestResult(
        repo_id=repo_id,
        revision=revision,
        found=True,
        # Defaults to False: absence of a positive signal must never read as "scanned".
        scans_done=bool(scan_payload.get("scansDone", False)),
        files=files,
        files_with_issues=[
            f.get("path", str(f)) if isinstance(f, dict) else str(f)
            for f in (scan_payload.get("filesWithIssues") or [])
        ],
        raw={"tree": tree, "scan": scan_payload},
    )
