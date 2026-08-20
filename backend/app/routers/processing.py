"""Processing-algorithm catalog (Module 2).

Mounted with no prefix — `GET /processing/algorithms`.

Serves the code-side algorithm registry so the frontend's pipeline builder
can render a typed input per parameter (with labels, defaults and ranges)
instead of asking scientists to hand-write JSON. Public and unauthenticated:
which preprocessing steps the platform supports is part of deciding whether
to sign up at all, and knowing the catalog grants no access to any data.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.processing.algorithms.registry import ALGORITHM_SPECS

router = APIRouter(prefix="/processing", tags=["processing"])

# Ordered as a sane default pipeline reads top to bottom: remove artifacts,
# then smooth, then subtract background, then normalize, then reshape the
# axis. The frontend groups its picker by these, so the order is UI-visible.
CATEGORY_ORDER = ["despiking", "smoothing", "baseline", "normalization", "axis"]


class AlgorithmInfo(BaseModel):
    step_type: str
    version: str
    label: str
    category: str
    description: str
    param_schema: dict
    transforms_axis: bool


class AlgorithmCatalog(BaseModel):
    categories: list[str]
    algorithms: list[AlgorithmInfo]


@router.get("/algorithms", response_model=AlgorithmCatalog)
def list_algorithms() -> AlgorithmCatalog:
    algorithms = [
        AlgorithmInfo(
            step_type=spec.step_type,
            version=spec.version,
            label=spec.label,
            category=spec.category,
            description=spec.description,
            param_schema=spec.param_schema,
            transforms_axis=spec.transforms_axis,
        )
        for spec in ALGORITHM_SPECS
    ]
    algorithms.sort(key=lambda a: (CATEGORY_ORDER.index(a.category), a.label))
    return AlgorithmCatalog(categories=CATEGORY_ORDER, algorithms=algorithms)
