"""The merged active-policy view the UI reads on most pages.

Version history and editing live under /api/policies; this endpoint is the convenient
"what governs a run right now" summary across all three asset classes.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.scoring.policy import get_active_policy

router = APIRouter(tags=["policy"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/policy")
def read_policy(settings: SettingsDep, session: SessionDep) -> dict[str, Any]:
    policy = get_active_policy(session)
    return {
        # Per-class governing versions. Recorded on every run so a decision stays
        # interpretable after the policy is edited (edits create new versions).
        "classes": {
            asset_type.value: {
                "version": meta.version,
                "content_hash": meta.content_hash,
            }
            for asset_type, meta in policy.meta.items()
        },
        "judge": {
            "default_model": policy.judge_default_model,
            "max_refusal_rate": policy.judge_max_refusal_rate,
        },
        # Both default to local models so nothing bills by accident.
        "default_subject_model": settings.default_subject_model,
        "scanner_model": settings.scanner_model,
        "llm_gates": {
            check_id: {
                "metric": gate.metric,
                "direction": gate.direction.value,
                "threshold": gate.threshold,
                "samples": gate.samples,
                "sample_ids_count": len(gate.sample_ids),
                "uses_core_set": bool(gate.sample_ids),
                "planned_samples": gate.planned_samples,
                "description": gate.description,
            }
            for check_id, gate in policy.llm_gates.items()
        },
        "composite_weights": policy.composite_weights,
        "composite_is_display_only": True,
        "scanner": {
            asset_type.value: {
                "block_on": sorted(s.value for s in sp.block_on),
                "trust_scanner_verdict": sp.trust_scanner_verdict,
                "max_source_files": sp.max_source_files,
            }
            for asset_type, sp in policy.scanner.items()
        },
        "thresholds_are_calibrated": False,
        "calibration_note": (
            "LLM thresholds are structurally correct but not yet calibrated. Calibration "
            "needs runs against models whose behaviour the org actually cares about; local "
            "models cannot stand in for that. Saving a new policy version is the only step "
            "required."
        ),
    }
