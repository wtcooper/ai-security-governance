"""Runtime configuration.

Everything the compute engines need to reach a model is expressed as an OpenAI-compatible
base URL plus an API key. There is deliberately no provider-specific setting here — no
OPENAI_MODEL, no ANTHROPIC_API_KEY. Pointing this at a different gateway (a work LiteLLM
instance, a local vLLM, or api.openai.com directly) is a two-variable change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _data_dir() -> Path:
    return Path(os.environ.get("APP_DATA_DIR", _REPO_ROOT / "data"))


@dataclass(frozen=True)
class Settings:
    # --- The one gateway every engine talks to -------------------------------
    gateway_base_url: str
    gateway_api_key: str
    # Inspect addresses the gateway as `openai-api/<provider>/<alias>`; this is <provider>.
    # The matching GATEWAY_BASE_URL / GATEWAY_API_KEY env vars are what Inspect reads.
    gateway_provider: str
    default_judge_model: str
    # Pre-selected subject model in the UI. Local on purpose: the form must not default to a
    # paid model, or a mis-click starts a billed run.
    default_subject_model: str
    # Model the Cisco scanners use for their LLM-as-judge analyzers. Separate from the eval
    # judge because the two jobs differ: one grades benchmark answers, the other reasons about
    # code. Local by default so a scan costs nothing.
    scanner_model: str

    # --- Storage ------------------------------------------------------------
    db_path: Path
    artifact_dir: Path
    workspace_dir: Path
    # Directory holding the per-asset-class policy seed files (llm.yaml, mcp.yaml,
    # skill.yaml). After first startup the governing copies live in the database.
    policy_dir: Path
    fixtures_dir: Path

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def submission_roots(self) -> list[Path]:
        """The only places a non-URL submission may point at.

        Uploads land in the first; the bundled poisoned fixtures live in the second so the
        acceptance suite can verify detection without network access.
        """
        return [self.workspace_dir / "uploads", self.fixtures_dir]

    @property
    def gateway_health_url(self) -> str:
        """Readiness endpoint, derived from the base URL by dropping the /v1 suffix."""
        root = self.gateway_base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        return f"{root}/health/readiness"

    def inspect_model_string(self, alias: str) -> str:
        """Gateway alias -> the model string Inspect AI understands."""
        return f"openai-api/{self.gateway_provider}/{alias}"


@lru_cache
def get_settings() -> Settings:
    data = _data_dir()
    settings = Settings(
        gateway_base_url=os.environ.get("GATEWAY_BASE_URL", "http://localhost:4000/v1"),
        gateway_api_key=os.environ.get("GATEWAY_API_KEY", "sk-local"),
        gateway_provider=os.environ.get("GATEWAY_PROVIDER", "gateway"),
        # Local by default: routine development and the end-to-end suite must not spend
        # money. Point this at gpt-5.6-luna for real calibration runs.
        default_judge_model=os.environ.get("DEFAULT_JUDGE_MODEL", "qwen35"),
        default_subject_model=os.environ.get("DEFAULT_SUBJECT_MODEL", "gemma4"),
        scanner_model=os.environ.get("SCANNER_MODEL", "gemma4"),
        db_path=Path(os.environ.get("DB_PATH", data / "governance.db")),
        artifact_dir=Path(os.environ.get("ARTIFACT_DIR", data / "artifacts")),
        workspace_dir=Path(os.environ.get("WORKSPACE_DIR", data / "workspaces")),
        policy_dir=Path(os.environ.get("POLICY_DIR", _REPO_ROOT / "backend/policy")),
        fixtures_dir=Path(
            os.environ.get("FIXTURES_DIR", _REPO_ROOT / "backend/tests/fixtures")
        ),
    )
    # The uploads directory is created eagerly because it is one of the two roots a
    # submission may point at, and an allowlist root that does not exist is easy to misread.
    for directory in (
        settings.db_path.parent,
        settings.artifact_dir,
        settings.workspace_dir,
        settings.workspace_dir / "uploads",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return settings
