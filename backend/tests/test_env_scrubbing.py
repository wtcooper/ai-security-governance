"""Provider credentials must never reach an eval subprocess.

Acceptance criterion 0.9. This is the regression test for the project's known failure mode:
`inspect_evals` tasks default their graders to hardcoded provider models such as
`openai/gpt-4o-mini`. If a provider key is present in the child environment, an
un-overridden default silently bills a real provider instead of failing loudly.

Pure-logic test on purpose — it asserts what the child environment contains, which no
amount of real traffic would reveal.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.engines.inspect_child import scrub_provider_credentials
from app.engines.inspect_runner import build_child_env

LEAKY_ENV = {
    "OPENAI_API_KEY": "sk-real-openai",
    "ANTHROPIC_API_KEY": "sk-ant-real",
    "GEMINI_API_KEY": "AQ.real-gemini",
    "GOOGLE_API_KEY": "AIza-real",
    "AZURE_OPENAI_API_KEY": "azure-real",
    "AWS_SECRET_ACCESS_KEY": "aws-real",
    "AWS_ACCESS_KEY_ID": "aws-id",
    "HF_TOKEN": "hf_real",
    "MISTRAL_API_KEY": "mistral-real",
    "COHERE_API_KEY": "cohere-real",
    "GROQ_API_KEY": "groq-real",
}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        gateway_base_url="http://gateway:4000/v1",
        gateway_api_key="sk-local",
        gateway_provider="gateway",
        default_judge_model="qwen35",
        db_path=tmp_path / "db.sqlite",
        artifact_dir=tmp_path / "artifacts",
        workspace_dir=tmp_path / "workspaces",
        policy_path=tmp_path / "policy.yaml",
    )


def test_every_provider_credential_is_stripped():
    cleaned = scrub_provider_credentials({**LEAKY_ENV, "PATH": "/usr/bin"})
    for key in LEAKY_ENV:
        assert key not in cleaned, f"{key} survived scrubbing"
    assert cleaned["PATH"] == "/usr/bin", "unrelated env must be preserved"


def test_gateway_credentials_are_preserved():
    cleaned = scrub_provider_credentials(
        {"GATEWAY_API_KEY": "sk-local", "GATEWAY_BASE_URL": "http://gateway:4000/v1"}
    )
    assert cleaned["GATEWAY_API_KEY"] == "sk-local"
    assert cleaned["GATEWAY_BASE_URL"] == "http://gateway:4000/v1"


def test_child_env_has_only_the_gateway_key(tmp_path, monkeypatch):
    for key, value in LEAKY_ENV.items():
        monkeypatch.setenv(key, value)

    env = build_child_env(_settings(tmp_path))

    api_keys = {k for k in env if k.endswith(("_API_KEY", "_TOKEN", "_SECRET_ACCESS_KEY"))}
    assert api_keys == {"GATEWAY_API_KEY"}, f"unexpected credentials in child env: {api_keys}"

    # Inspect resolves openai-api/gateway/<alias> from exactly this pair, which is why one
    # mechanism covers the subject model and every judge model.
    assert env["GATEWAY_BASE_URL"] == "http://gateway:4000/v1"
    assert env["GATEWAY_API_KEY"] == "sk-local"

    assert not any(value.startswith(("sk-real", "sk-ant", "AQ.", "AIza")) for value in env.values())
