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

    # --- Storage ------------------------------------------------------------
    db_path: Path
    artifact_dir: Path
    workspace_dir: Path
    policy_path: Path

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

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
        db_path=Path(os.environ.get("DB_PATH", data / "governance.db")),
        artifact_dir=Path(os.environ.get("ARTIFACT_DIR", data / "artifacts")),
        workspace_dir=Path(os.environ.get("WORKSPACE_DIR", data / "workspaces")),
        policy_path=Path(os.environ.get("POLICY_PATH", _REPO_ROOT / "backend/policy/policy.yaml")),
    )
    for directory in (settings.db_path.parent, settings.artifact_dir, settings.workspace_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return settings
