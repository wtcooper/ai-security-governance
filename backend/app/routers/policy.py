"""Exposing the policy so the UI can show what a threshold actually is."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.scoring.policy import get_policy

router = APIRouter(tags=["policy"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("/policy")
def read_policy(settings: SettingsDep) -> dict[str, Any]:
    policy = get_policy(settings.policy_path)
    return {
        "version": policy.version,
        # Recorded on every run so a decision stays interpretable after this file is edited.
        "content_hash": policy.content_hash,
        "judge": {
            "default_model": policy.judge_default_model,
            "max_refusal_rate": policy.judge_max_refusal_rate,
        },
        "llm_gates": {
            check_id: {
                "metric": gate.metric,
                "direction": gate.direction.value,
                "threshold": gate.threshold,
                "description": gate.description,
            }
            for check_id, gate in policy.llm_gates.items()
        },
        "composite_weights": policy.composite_weights,
        "composite_is_display_only": True,
        "scanner": {
            asset_type.value: {
                "mode": sp.mode,
                "block_on": sorted(s.value for s in sp.block_on),
                "trust_scanner_verdict": sp.trust_scanner_verdict,
            }
            for asset_type, sp in policy.scanner.items()
        },
        "thresholds_are_calibrated": False,
        "calibration_note": (
            "LLM thresholds are structurally correct but not yet calibrated. Calibration "
            "needs runs against models whose behaviour the org actually cares about; local "
            "models cannot stand in for that. Editing policy.yaml is the only step required."
        ),
    }
