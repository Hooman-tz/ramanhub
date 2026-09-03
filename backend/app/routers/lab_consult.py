"""Read-only "lab consultant" LLM endpoint — `POST /v1/lab/consult`.

Strictly scoped: it looks at a COMPACT summary of the caller's *own* spectra
(counts, wavenumber ranges, point counts, modality, existing ledger step
types, basic intensity statistics) and asks the shared model for
data-processing advice — suggested preprocessing steps and analyses, with
rationales and caveats.

Hard boundaries this module keeps:

* Auth is `get_current_full_user` (same as the other identity-carrying
  routers), plus the LLM rate-limit dependency.
* It resolves ids ONLY to spectra owned by the caller; anything else is a
  404 (never 403), matching `app.processing.state_machine`'s
  404-not-403 convention.
* The model never sees raw spectral arrays, other users' data, file bytes,
  or DB handles — only the derived scalar summary assembled here.
* ZERO side effects: no ledgers, no cache rows, no spectrum mutation, no
  jobs enqueued. This endpoint only reads.
* Model output is post-filtered against
  `app.processing.algorithms.registry` (the 13 registered algorithms) and
  the supported analysis types before it is returned.

This lives in `app/routers/` (not `app/processing/` or `app/ingestion/`) —
it imports from the processing package but adds nothing to it.
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user
from app.db.session import get_db
from app.llm import LLMError, complete_json, llm_configured
from app.models.analysis import AnalysisDataset, AnalysisDatasetSpectrum
from app.models.processing_ledger import ProcessingLedger
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.algorithms.registry import ALGORITHM_REGISTRY
from app.ratelimit import rate_limit_llm_consult
from app.raman_contract import RamanDataError
from app.spectra_io import load_raw_spectrum

router = APIRouter(prefix="/v1/lab", tags=["lab-consult"])
logger = logging.getLogger(__name__)

# Analysis types the analysis engine can actually run — kept in lockstep with
# `app.routers.analysis.RunCreate.analysis_type` / `app.analysis.engine`.
# Imported as a literal here rather than from the analysis router to avoid a
# router import cycle.
SUPPORTED_ANALYSIS_TYPES: frozenset[str] = frozenset({"pca", "pca_kmeans"})

# Bound how many per-spectrum summaries we put in the prompt. The aggregate
# counts still cover everything; this only caps the itemised list.
_MAX_SPECTRA_IN_PROMPT = 25
_MAX_QUESTION_CHARS = 500
_MAX_TOKENS = 1200

_SYSTEM_PROMPT = (
    "You are a Raman spectroscopy data-processing consultant embedded in the "
    "Spectra Insight platform. You are given a compact, anonymised statistical "
    "summary of spectra that belong to the user who is asking. Your ONLY job is "
    "to advise on preprocessing and analysis of THESE spectra: which "
    "preprocessing steps to apply and why, which analyses might be informative, "
    "and what caveats to keep in mind. "
    "You must refuse anything else. If the user asks about other people's data, "
    "asks you to write code, run jobs, modify or publish spectra, retrieve raw "
    "data, or anything unrelated to processing their own spectra, do not comply "
    "— instead add a short note to `caveats` explaining you can only advise on "
    "processing the user's own spectra. "
    "Only suggest preprocessing `step_type` values from the provided "
    "`registered_algorithms` list, and only suggest `analysis_type` values from "
    "the provided `supported_analysis_types` list. Never invent step or "
    "analysis types. Keep every string short and specific. This is advice only; "
    "you are not changing anything."
)

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "observations": {"type": "array", "items": {"type": "string"}},
        "suggested_preprocessing": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_type": {"type": "string"},
                    "params": {"type": "object"},
                    "rationale": {"type": "string"},
                },
                "required": ["step_type", "rationale"],
            },
        },
        "suggested_analyses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "analysis_type": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["analysis_type", "rationale"],
            },
        },
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "observations",
        "suggested_preprocessing",
        "suggested_analyses",
        "caveats",
    ],
}


# --- request / response shapes --------------------------------------------


class LabConsultRequest(BaseModel):
    dataset_id: UUID | None = None
    spectrum_ids: list[UUID] | None = None
    question: str | None = Field(default=None, max_length=_MAX_QUESTION_CHARS)


class SuggestedPreprocessing(BaseModel):
    step_type: str
    params: dict
    rationale: str


class SuggestedAnalysis(BaseModel):
    analysis_type: str
    rationale: str


class LabConsultResponse(BaseModel):
    observations: list[str]
    suggested_preprocessing: list[SuggestedPreprocessing]
    suggested_analyses: list[SuggestedAnalysis]
    caveats: list[str]


# --- helpers -------------------------------------------------------------


def _not_found() -> HTTPException:
    # 404, never 403 — a non-owner must not be able to tell "isn't yours"
    # from "doesn't exist". Mirrors app.processing.state_machine.
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _resolve_owned_spectra(
    body: LabConsultRequest, user: User, db: Session
) -> list[Spectrum]:
    """Resolve the request's `dataset_id` / `spectrum_ids` to Spectrum rows
    owned by `user`. Any id that doesn't resolve to one of the caller's
    spectra raises 404."""
    ids: list[UUID] = []
    seen: set[UUID] = set()

    if body.dataset_id is not None:
        dataset = db.get(AnalysisDataset, body.dataset_id)
        if dataset is None or dataset.owner_id != user.id:
            raise _not_found()
        rows = (
            db.query(AnalysisDatasetSpectrum)
            .filter(AnalysisDatasetSpectrum.dataset_id == dataset.id)
            .order_by(AnalysisDatasetSpectrum.position)
            .all()
        )
        for row in rows:
            if row.spectrum_id not in seen:
                seen.add(row.spectrum_id)
                ids.append(row.spectrum_id)

    for sid in body.spectrum_ids or []:
        if sid not in seen:
            seen.add(sid)
            ids.append(sid)

    if not ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide dataset_id and/or spectrum_ids to consult on.",
        )

    spectra: list[Spectrum] = []
    for sid in ids:
        spectrum = db.get(Spectrum, sid)
        if spectrum is None or spectrum.owner_id != user.id:
            raise _not_found()
        spectra.append(spectrum)
    return spectra


def _ledger_step_types(spectrum: Spectrum, db: Session) -> list[str]:
    if spectrum.current_ledger_id is None:
        return []
    ledger = db.get(ProcessingLedger, spectrum.current_ledger_id)
    if ledger is None or not isinstance(ledger.steps, list):
        return []
    out: list[str] = []
    for step in ledger.steps:
        if isinstance(step, dict) and isinstance(step.get("type"), str):
            out.append(step["type"])
    return out


def _intensity_stats(intensities: np.ndarray) -> dict | None:
    if intensities.size == 0:
        return None
    finite = intensities[np.isfinite(intensities)]
    if finite.size == 0:
        return None
    return {
        "min": round(float(np.min(finite)), 6),
        "max": round(float(np.max(finite)), 6),
        "mean": round(float(np.mean(finite)), 6),
        "std": round(float(np.std(finite)), 6),
    }


def _summarize(spectra: list[Spectrum], db: Session) -> dict:
    """Build the COMPACT, scalar-only summary sent to the model. Never
    includes raw arrays, file bytes, other users' data, or DB handles."""
    modality_counts: dict[str, int] = {}
    all_step_types: set[str] = set()
    per_spectrum: list[dict] = []

    for spectrum in spectra:
        modality = getattr(spectrum.modality, "value", str(spectrum.modality))
        modality_counts[modality] = modality_counts.get(modality, 0) + 1

        step_types = _ledger_step_types(spectrum, db)
        all_step_types.update(step_types)

        entry: dict = {
            "modality": modality,
            "ledger_step_types": step_types,
            "point_count": None,
            "wavenumber_min": None,
            "wavenumber_max": None,
            "intensity_stats": None,
        }
        raw_file = db.get(RawFile, spectrum.raw_file_id)
        if raw_file is not None:
            try:
                wavenumbers, intensities = load_raw_spectrum(raw_file)
            except (RamanDataError, ValueError, OSError, KeyError):
                wavenumbers = intensities = np.asarray([], dtype=float)
            if wavenumbers.size:
                entry["point_count"] = int(wavenumbers.shape[0])
                entry["wavenumber_min"] = round(float(np.min(wavenumbers)), 4)
                entry["wavenumber_max"] = round(float(np.max(wavenumbers)), 4)
                entry["intensity_stats"] = _intensity_stats(intensities)

        if len(per_spectrum) < _MAX_SPECTRA_IN_PROMPT:
            per_spectrum.append(entry)

    registered = [
        {
            "step_type": spec.step_type,
            "label": spec.label,
            "category": spec.category,
            "param_schema": spec.param_schema,
        }
        for spec in ALGORITHM_REGISTRY.values()
    ]

    return {
        "spectra_count": len(spectra),
        "modality_counts": modality_counts,
        "existing_ledger_step_types": sorted(all_step_types),
        "spectra": per_spectrum,
        "spectra_omitted_from_list": max(0, len(spectra) - _MAX_SPECTRA_IN_PROMPT),
        "registered_algorithms": registered,
        "supported_analysis_types": sorted(SUPPORTED_ANALYSIS_TYPES),
    }


def _coerce_scalar(value: object, expected: str | None) -> object | None:
    """Best-effort coerce `value` to the JSON-Schema `type` the param
    declares. Returns None when it can't be coerced (caller drops the
    param)."""
    if expected == "integer":
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None
    if expected == "number":
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return None
        return None
    if expected == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            return value.strip().lower() == "true"
        return None
    if expected == "string":
        return value if isinstance(value, str) else None
    if expected == "array":
        return value if isinstance(value, list) else None
    if expected == "object":
        return value if isinstance(value, dict) else None
    # No declared type — pass the value through untouched.
    return value


def _coerce_params(raw_params: object, param_schema: dict) -> dict:
    """Keep only params that appear in the algorithm's `param_schema`,
    coerced to the declared type and within any declared bounds/enum.
    Everything else is dropped."""
    if not isinstance(raw_params, dict):
        return {}
    properties = (param_schema or {}).get("properties", {}) or {}
    out: dict = {}
    for key, value in raw_params.items():
        prop = properties.get(key)
        if not isinstance(prop, dict) or value is None:
            continue
        coerced = _coerce_scalar(value, prop.get("type"))
        if coerced is None:
            continue
        if isinstance(coerced, (int, float)) and not isinstance(coerced, bool):
            minimum = prop.get("minimum")
            maximum = prop.get("maximum")
            if minimum is not None and coerced < minimum:
                continue
            if maximum is not None and coerced > maximum:
                continue
        enum = prop.get("enum")
        if isinstance(enum, list) and coerced not in enum:
            continue
        out[key] = coerced
    return out


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _filter_output(raw: dict) -> LabConsultResponse:
    """Post-filter model output: drop unknown step types, coerce params,
    drop unsupported analysis types."""
    preprocessing: list[SuggestedPreprocessing] = []
    for item in raw.get("suggested_preprocessing") or []:
        if not isinstance(item, dict):
            continue
        step_type = item.get("step_type")
        spec = ALGORITHM_REGISTRY.get(step_type) if isinstance(step_type, str) else None
        if spec is None:
            continue
        rationale = item.get("rationale")
        preprocessing.append(
            SuggestedPreprocessing(
                step_type=step_type,
                params=_coerce_params(item.get("params"), spec.param_schema),
                rationale=rationale if isinstance(rationale, str) else "",
            )
        )

    analyses: list[SuggestedAnalysis] = []
    for item in raw.get("suggested_analyses") or []:
        if not isinstance(item, dict):
            continue
        analysis_type = item.get("analysis_type")
        if analysis_type not in SUPPORTED_ANALYSIS_TYPES:
            continue
        rationale = item.get("rationale")
        analyses.append(
            SuggestedAnalysis(
                analysis_type=analysis_type,
                rationale=rationale if isinstance(rationale, str) else "",
            )
        )

    return LabConsultResponse(
        observations=_as_str_list(raw.get("observations")),
        suggested_preprocessing=preprocessing,
        suggested_analyses=analyses,
        caveats=_as_str_list(raw.get("caveats")),
    )


# --- endpoint ----------------------------------------------------------


@router.post("/consult", response_model=LabConsultResponse)
async def lab_consult(
    body: LabConsultRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_llm_consult),
) -> LabConsultResponse:
    """Read-only processing advice for the caller's own spectra. No side
    effects: nothing is created, mutated, cached, or enqueued."""
    if not llm_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Lab consultant is unavailable (no LLM configured).",
        )

    spectra = _resolve_owned_spectra(body, user, db)
    summary = _summarize(spectra, db)

    user_message = "Spectra summary:\n" + json.dumps(summary, default=str)
    if body.question:
        user_message += f"\n\nUser question (advise only if it is about processing these spectra):\n{body.question}"

    try:
        raw = await complete_json(
            system=_SYSTEM_PROMPT,
            user=user_message,
            schema=_OUTPUT_SCHEMA,
            max_tokens=_MAX_TOKENS,
            temperature=0.0,
        )
    except LLMError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Lab consultant call failed: {exc}",
        ) from exc

    return _filter_output(raw)
