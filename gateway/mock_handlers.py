"""Mock LiteLLM providers so the whole pipeline runs with zero API keys.

Ported from ai-security-evals/targets/proxy/mock_handlers.py and trimmed to what this
project needs: the guardrail A/B/C toggling machinery and the judge-envelope classifier
belonged to that repo's control-benchmarking harness, not to governance scoring.

What remains registers two custom providers with the proxy:

1. MockTargetLLM  — canned subject-model responses selected by model name suffix.
2. MockJudgeLLM   — a fixed, obviously-synthetic grade.

These prove wiring only. `mock-judge` must never be used to produce a real score: it does
not read the response it is grading. The gateway ships `gpt-5.6-luna` as the real default
judge for that.
"""

from __future__ import annotations

import time
import uuid

from litellm import CustomLLM
from litellm.exceptions import BadRequestError
from litellm.types.utils import Choices, Message, ModelResponse, Usage

_COMPLIANT_TEXT = (
    "Sure, here is a substantive answer to your request. This is a deterministic mock "
    "response used to prove gateway wiring."
)
_REFUSAL_TEXT = (
    "I can't help with that request. This is a deterministic mock response used to prove "
    "gateway wiring."
)


def _make_response(model: str, content: str) -> ModelResponse:
    """Build a minimal OpenAI-shaped ModelResponse for a mock completion."""
    return ModelResponse(
        id=f"mock-{uuid.uuid4().hex[:12]}",
        created=int(time.time()),
        model=model,
        object="chat.completion",
        choices=[
            Choices(
                index=0,
                finish_reason="stop",
                message=Message(role="assistant", content=content),
            )
        ],
        usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )


class MockTargetLLM(CustomLLM):
    """Routes a model-name suffix to a canned response or a simulated policy block.

    Suffixes (after the ``mock-target/`` provider prefix):
        compliant     -> 200 with substantive text
        refusal       -> 200 with refusal text
        policy-block  -> 400 mimicking a content_policy_violation envelope
    """

    @staticmethod
    def _route(model: str) -> str:
        # LiteLLM strips the provider prefix, but tolerate the full form too.
        return model.split("/", 1)[-1].strip().lower()

    def completion(self, *args, **kwargs) -> ModelResponse:
        model = kwargs.get("model", "")
        kind = self._route(model)
        if kind == "policy-block":
            raise BadRequestError(
                message=(
                    "Your request was rejected as a result of our safety system. Mock "
                    "content_policy_violation envelope for wiring tests."
                ),
                model=model,
                llm_provider="mock-target",
            )
        if kind == "refusal":
            return _make_response(model, _REFUSAL_TEXT)
        return _make_response(model, _COMPLIANT_TEXT)

    async def acompletion(self, *args, **kwargs) -> ModelResponse:
        return self.completion(*args, **kwargs)


class MockJudgeLLM(CustomLLM):
    """A judge stand-in that always returns the same grade.

    Deliberately does NOT inspect what it is grading. Any run whose judge is `mock-judge`
    is a wiring test, and the backend records the judge model on the run so such results
    are never mistaken for a real evaluation.
    """

    def completion(self, *args, **kwargs) -> ModelResponse:
        return _make_response(
            kwargs.get("model", "mock-judge"),
            "MOCK JUDGE - wiring proof only, not a real grade. Verdict: C",
        )

    async def acompletion(self, *args, **kwargs) -> ModelResponse:
        return self.completion(*args, **kwargs)


# Module-level singletons referenced from litellm_config.yaml custom_provider_map.
mock_target_llm = MockTargetLLM()
mock_judge_llm = MockJudgeLLM()
