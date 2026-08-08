"""All compute engines must live in one venv, at safe versions.

This is a regression test for two facts established during planning:

1. `litellm[proxy]` and `inspect-ai` genuinely cannot share a venv — the proxy extra
   requires boto3>=1.43.1 while inspect-ai requires aioboto3>=13.0.0, which caps
   boto3<1.40.62. That is why the LiteLLM *gateway* runs in its own container. The plain
   `litellm` library, however, coexists fine, so the Cisco scanners (which use litellm as
   a library) install alongside Inspect. If this test starts failing, that assumption
   broke and the packaging decision needs revisiting.

2. litellm 1.82.7 and 1.82.8 were malicious (TeamPCP supply-chain compromise,
   2026-03-24). litellm arrives here transitively via both Cisco scanners, so the floor
   is asserted rather than assumed.
"""

import importlib.metadata as md

SAFE_LITELLM_FLOOR = (1, 83, 0)
MALICIOUS_LITELLM = {"1.82.7", "1.82.8"}


def _version_tuple(raw: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in raw.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def test_all_engines_import_in_one_process():
    """Resolver success is not enough — the imports have to actually work together."""
    import inspect_ai
    import inspect_evals  # noqa: F401
    import litellm  # noqa: F401
    import mcpscanner  # noqa: F401
    import skill_scanner  # noqa: F401

    assert inspect_ai.__version__


def test_litellm_is_not_a_malicious_release():
    version = md.version("litellm")
    assert version not in MALICIOUS_LITELLM, (
        f"litellm {version} is a known-malicious release (TeamPCP, 2026-03-24)"
    )
    assert _version_tuple(version) >= SAFE_LITELLM_FLOOR, (
        f"litellm {version} is below the safe floor 1.83.0"
    )


def test_litellm_proxy_extra_is_absent():
    """The proxy extra must NOT be installed here; it belongs to the gateway container.

    Its presence would mean the boto3 conflict was resolved by degrading inspect-ai.
    """
    assert _version_tuple(md.version("boto3")) < (1, 43, 1), (
        "boto3>=1.43.1 suggests litellm[proxy] leaked into the backend venv"
    )
