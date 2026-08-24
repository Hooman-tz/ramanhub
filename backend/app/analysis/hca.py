"""Hierarchical cluster analysis over a set of spectra.

The companion to PCA: PCA tells you what varies, HCA tells you what groups.
Together they are the whole of the "unsupervised exploration" the
architecture doc scopes the platform to.

`correlation` distance is the default rather than `euclidean` because it is
invariant to overall intensity scale — two measurements of the same material
taken at different laser powers or integration times are the *same sample*
scientifically, and euclidean distance would put them far apart purely on
brightness. Ward linkage is the default because it produces the compact,
evenly-sized clusters that read well on a dendrogram; note that Ward is only
strictly defined for euclidean distance, so it is paired with euclidean and
silently unavailable otherwise (see `LINKAGE_METHODS`).

Returns a serializable dendrogram (scipy's linkage matrix plus a leaf
ordering) rather than a plot, so the frontend draws it and a recorded
Finding stays reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.cluster.hierarchy import dendrogram, fcluster, linkage
from scipy.spatial.distance import pdist

from app.analysis.common_grid import build_common_grid

VERSION = "1.0.0"

# Ward requires euclidean distance — scipy warns and produces a meaningless
# result otherwise, so the router validates the pairing rather than letting
# a user build a plot that quietly means nothing.
LINKAGE_METHODS = ("ward", "average", "complete", "single")
DISTANCE_METRICS = ("correlation", "euclidean", "cosine", "cityblock")
EUCLIDEAN_ONLY_METHODS = frozenset({"ward"})

PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "metric": {
            "type": "string",
            "enum": list(DISTANCE_METRICS),
            "default": "correlation",
            "title": "Distance metric",
            "description": "Correlation ignores overall intensity scale, so the same material "
            "measured at two laser powers still clusters together. Euclidean does not.",
        },
        "method": {
            "type": "string",
            "enum": list(LINKAGE_METHODS),
            "default": "average",
            "title": "Linkage",
            "description": "How cluster-to-cluster distance is defined. Ward requires the "
            "euclidean metric.",
        },
        "n_clusters": {
            "type": ["integer", "null"],
            "minimum": 2,
            "maximum": 50,
            "default": None,
            "title": "Cut into N clusters",
            "description": "Optional. Cuts the tree to assign each spectrum a cluster label.",
        },
    },
}

DEFAULTS = {"metric": "correlation", "method": "average", "n_clusters": None}


class InvalidLinkageError(ValueError):
    """Raised for a metric/method pairing that scipy can't honour."""


@dataclass(frozen=True)
class HcaResult:
    linkage_matrix: list[list[float]]
    """scipy's (N-1, 4) linkage matrix: [left, right, distance, count]."""
    leaf_order: list[int]
    """Indices of the input spectra in dendrogram left-to-right order — what
    the frontend needs to lay the tree out without recomputing it."""
    labels: list[int] | None
    """Cluster assignment per input spectrum, when `n_clusters` was given."""
    distances: list[float]
    """Condensed pairwise distance vector, for a similarity heatmap."""
    n_spectra: int


def run_hca(
    spectra: list[tuple[np.ndarray, np.ndarray]],
    metric: str = "correlation",
    method: str = "average",
    n_clusters: int | None = None,
) -> HcaResult:
    """Cluster `spectra`. Raises `InvalidLinkageError` for an impossible
    metric/method pairing, or `IncompatibleSpectraError` (from
    `common_grid`) if the inputs share no wavenumber range."""
    if method not in LINKAGE_METHODS:
        raise InvalidLinkageError(f"Unknown linkage method: {method!r}")
    if metric not in DISTANCE_METRICS:
        raise InvalidLinkageError(f"Unknown distance metric: {metric!r}")
    if method in EUCLIDEAN_ONLY_METHODS and metric != "euclidean":
        raise InvalidLinkageError(
            f"{method!r} linkage is only defined for the euclidean metric, not {metric!r}. "
            f"Use 'average' linkage with {metric!r}, or switch the metric to 'euclidean'."
        )

    _grid, matrix = build_common_grid(spectra)
    n_spectra = matrix.shape[0]

    condensed = pdist(matrix, metric=metric)
    # A flat spectrum has zero variance, making correlation distance NaN;
    # scipy's linkage then produces an all-NaN tree rather than failing
    # loudly. Treat an undefined pair as maximally distant instead.
    condensed = np.nan_to_num(condensed, nan=float(np.nanmax(condensed, initial=1.0)))

    z = linkage(condensed, method=method)
    tree = dendrogram(z, no_plot=True)

    labels = None
    if n_clusters is not None:
        k = int(np.clip(n_clusters, 2, n_spectra))
        labels = [int(v) for v in fcluster(z, t=k, criterion="maxclust")]

    return HcaResult(
        linkage_matrix=[[float(v) for v in row] for row in z],
        leaf_order=[int(v) for v in tree["leaves"]],
        labels=labels,
        distances=[float(v) for v in condensed],
        n_spectra=n_spectra,
    )
