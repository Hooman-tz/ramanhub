"""Principal component analysis over a set of spectra.

The architecture doc scopes the platform to "unsupervised exploration
(PCA-style)" and explicitly *not* model training — so this returns scores,
loadings and explained variance for the user to look at, and nothing is
persisted as a model or used to make a prediction.

Implemented directly on `numpy.linalg.svd` rather than pulling in
scikit-learn. Two reasons: PCA *is* a thin wrapper over an SVD, so the
dependency would buy nothing but weight (the doc asks for lean code built
for the scale we actually have); and sklearn's `PCA` always mean-centers
internally with no way to opt out, which would silently make the
`mean_center=False` parameter below a lie.

Preprocessing choices, both standard for spectroscopy and both exposed as
parameters because the right answer is sample-dependent:

- **Mean-centering** (default on). Without it PC1 almost always comes out as
  the corpus mean spectrum, which carries no between-sample information and
  wastes a component.
- **Scaling** (default off). Autoscaling each wavenumber to unit variance
  gives weak bands the same weight as strong ones. Occasionally what you
  want; usually it just amplifies noise in the empty regions of a Raman
  spectrum, so it is opt-in.

Spectra are aligned onto a shared axis first — see `common_grid`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.analysis.common_grid import build_common_grid

VERSION = "1.0.0"

PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "n_components": {
            "type": "integer",
            "minimum": 2,
            "maximum": 10,
            "default": 3,
            "title": "Components",
            "description": "Automatically reduced if you have fewer spectra than components.",
        },
        "mean_center": {
            "type": "boolean",
            "default": True,
            "title": "Mean-center",
            "description": "Subtract the average spectrum first. Leave on unless you know why "
            "you want PC1 to be the mean.",
        },
        "scale": {
            "type": "boolean",
            "default": False,
            "title": "Autoscale to unit variance",
            "description": "Gives weak bands equal weight to strong ones. Off by default — on "
            "Raman data it usually amplifies noise in the flat regions.",
        },
    },
}

DEFAULTS = {"n_components": 3, "mean_center": True, "scale": False}


@dataclass(frozen=True)
class PcaResult:
    wavenumbers: list[float]
    """The common axis the loadings are expressed on."""
    scores: list[list[float]]
    """(N spectra x K components) — where each spectrum sits in PC space."""
    loadings: list[list[float]]
    """(K components x P wavenumbers) — what each PC actually *is*,
    spectrally. This is the part that makes a PCA plot interpretable."""
    explained_variance_ratio: list[float]
    n_components: int
    n_spectra: int


def _deterministic_signs(scores: np.ndarray, loadings: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fix the arbitrary sign of each component.

    An SVD is only defined up to a simultaneous sign flip of a score column
    and its loading row, so the same data can legitimately produce a
    mirror-image plot on different runs, platforms or LAPACK builds. On a
    reproducibility platform that would be an unpleasant surprise ("my
    figure flipped"), so pin the convention the way sklearn does: make the
    largest-magnitude element of each loading vector positive.
    """
    dominant = np.argmax(np.abs(loadings), axis=1)
    signs = np.sign(loadings[np.arange(loadings.shape[0]), dominant])
    signs[signs == 0] = 1.0
    return scores * signs, loadings * signs[:, np.newaxis]


def run_pca(
    spectra: list[tuple[np.ndarray, np.ndarray]],
    n_components: int = 3,
    mean_center: bool = True,
    scale: bool = False,
) -> PcaResult:
    """Fit PCA over `spectra`. Raises `IncompatibleSpectraError` (from
    `common_grid`) if the inputs can't be put on a shared axis."""
    grid, matrix = build_common_grid(spectra)
    n_spectra, n_features = matrix.shape

    # A K-component decomposition can't exist above rank min(samples,
    # features), so clamp rather than error — asking for 3 components across
    # 2 spectra should give you 2, not a 500.
    effective = max(int(min(n_components, n_spectra, n_features)), 1)

    x = matrix.astype(float, copy=True)
    if mean_center:
        x -= x.mean(axis=0, keepdims=True)
    if scale:
        std = x.std(axis=0, keepdims=True)
        # Flat columns (a wavenumber where every spectrum agrees) would
        # divide by zero; leaving them unscaled is the standard fix.
        std[std == 0] = 1.0
        x /= std

    u, s, vt = np.linalg.svd(x, full_matrices=False)

    loadings = vt[:effective]
    scores = u[:, :effective] * s[:effective]
    scores, loadings = _deterministic_signs(scores, loadings)

    # Total variance uses the full singular spectrum, not just the retained
    # components — otherwise the ratios would always sum to 1.0 and tell you
    # nothing about how much you left behind.
    variances = (s**2) / max(n_spectra - 1, 1)
    total = float(variances.sum())
    ratios = (variances[:effective] / total) if total > 0 else np.zeros(effective)

    return PcaResult(
        wavenumbers=[float(v) for v in grid],
        scores=[[float(v) for v in row] for row in scores],
        loadings=[[float(v) for v in row] for row in loadings],
        explained_variance_ratio=[float(v) for v in ratios],
        n_components=effective,
        n_spectra=n_spectra,
    )
