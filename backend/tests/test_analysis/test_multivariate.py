"""PCA / HCA / common-grid tests.

These build spectra from two deliberately different "materials" so the
question each test asks has a known right answer: PC1 should separate the
groups, and HCA should cluster them.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.analysis.common_grid import (
    MAX_GRID_POINTS,
    IncompatibleSpectraError,
    build_common_grid,
)
from app.analysis.hca import InvalidLinkageError, run_hca
from app.analysis.pca import run_pca
from tests.test_algorithms._synthetic import gaussian


def _material(centers, n_points=400, lo=400.0, hi=1800.0, noise=0.0, seed=0, scale=1.0):
    x = np.linspace(lo, hi, n_points)
    y = np.zeros_like(x)
    for center in centers:
        y += gaussian(x, center, amplitude=100.0, width=15.0)
    if noise:
        y += np.random.default_rng(seed).normal(0, noise, size=y.shape)
    return x, y * scale


def _two_groups(n_each=4, noise=2.0):
    """n_each spectra of material A (bands at 600/1200) and n_each of
    material B (bands at 900/1500)."""
    a = [_material((600.0, 1200.0), noise=noise, seed=i) for i in range(n_each)]
    b = [_material((900.0, 1500.0), noise=noise, seed=100 + i) for i in range(n_each)]
    return a + b


# --------------------------------------------------------------------- grid


def test_common_grid_stacks_to_a_matrix():
    grid, matrix = build_common_grid(_two_groups(n_each=2))
    assert matrix.shape[0] == 4
    assert matrix.shape[1] == grid.size


def test_common_grid_uses_the_intersection_not_the_union():
    """Never extrapolate: the shared axis must sit inside every input's
    measured range."""
    narrow = _material((900.0,), lo=800.0, hi=1200.0)
    wide = _material((900.0,), lo=400.0, hi=1800.0)

    grid, _ = build_common_grid([narrow, wide])

    assert grid[0] == pytest.approx(800.0)
    assert grid[-1] == pytest.approx(1200.0)


def test_common_grid_rejects_non_overlapping_spectra():
    low = _material((500.0,), lo=400.0, hi=700.0)
    high = _material((1500.0,), lo=1200.0, hi=1800.0)

    with pytest.raises(IncompatibleSpectraError, match="no overlapping"):
        build_common_grid([low, high])


def test_common_grid_needs_two_spectra():
    with pytest.raises(IncompatibleSpectraError, match="at least 2"):
        build_common_grid([_material((900.0,))])


def test_common_grid_is_capped():
    huge = [_material((900.0,), n_points=20000) for _ in range(2)]
    grid, _ = build_common_grid(huge)
    assert grid.size <= MAX_GRID_POINTS


# ---------------------------------------------------------------------- PCA


def test_pca_shapes_line_up():
    spectra = _two_groups(n_each=3)
    result = run_pca(spectra, n_components=3)

    assert result.n_spectra == 6
    assert result.n_components == 3
    assert len(result.scores) == 6
    assert all(len(row) == 3 for row in result.scores)
    assert len(result.loadings) == 3
    assert all(len(row) == len(result.wavenumbers) for row in result.loadings)


def test_pca_explained_variance_is_ordered_and_bounded():
    result = run_pca(_two_groups(), n_components=3)
    ratios = result.explained_variance_ratio

    assert ratios == sorted(ratios, reverse=True)
    assert all(0.0 <= r <= 1.0 for r in ratios)
    assert sum(ratios) <= 1.0 + 1e-9


def test_pc1_separates_two_materials():
    """The whole point of offering PCA: two distinct materials must fall on
    opposite sides of PC1."""
    spectra = _two_groups(n_each=4)
    result = run_pca(spectra, n_components=2)

    pc1 = [row[0] for row in result.scores]
    group_a, group_b = pc1[:4], pc1[4:]

    assert max(group_a) < min(group_b) or max(group_b) < min(group_a)


def test_pc1_dominates_for_two_clean_groups():
    result = run_pca(_two_groups(n_each=4, noise=0.5), n_components=3)
    assert result.explained_variance_ratio[0] > 0.8


def test_components_are_clamped_to_the_rank():
    """Asking for more components than there are spectra returns what's
    possible instead of raising."""
    result = run_pca(_two_groups(n_each=1), n_components=10)
    assert result.n_components == 2


def test_mean_centering_is_actually_optional():
    """Guards the reason this isn't sklearn's PCA, whose `PCA` always
    centers with no way to opt out — so `mean_center=False` would silently
    be a lie.

    The tell is what PC1's loading *looks like*, not its variance share.
    Uncentered, PC1 points along the raw data's dominant direction, which
    is essentially the corpus mean spectrum. Centered, PC1 becomes a
    contrast between the two materials, which is uncorrelated with the
    mean. Comparing against the mean rather than checking signs pointwise
    keeps this robust to the low-level noise in the flat baseline regions.

    The shared offset below is load-bearing, not decoration. Two materials
    of equal magnitude and nothing in common produce two near-identical
    singular values, and within such a degenerate subspace the SVD basis is
    arbitrary — "PC1" is then free to come out as either material rather
    than the mean, and the assertion would be testing luck. A common
    baseline (which real spectra measured on one instrument genuinely
    share) makes the mean direction unambiguously dominant, so "PC1 is the
    mean" is a well-posed claim.
    """
    spectra = [(x, y + 500.0) for x, y in _two_groups(n_each=3, noise=0.5)]

    centered = np.asarray(run_pca(spectra, mean_center=True).loadings[0])
    uncentered = np.asarray(run_pca(spectra, mean_center=False).loadings[0])

    _grid, matrix = build_common_grid(spectra)
    mean_spectrum = matrix.mean(axis=0)

    def similarity_to_mean(loading: np.ndarray) -> float:
        # Absolute cosine similarity — PC sign is arbitrary by convention.
        denom = np.linalg.norm(loading) * np.linalg.norm(mean_spectrum)
        return abs(float(np.dot(loading, mean_spectrum) / denom))

    assert similarity_to_mean(uncentered) > 0.95, "uncentered PC1 should track the mean spectrum"
    assert similarity_to_mean(centered) < 0.2, "centered PC1 should be a contrast, not the mean"


def test_signs_are_deterministic_across_runs():
    """A figure must not flip between runs — the SVD sign convention is
    pinned on purpose."""
    spectra = _two_groups(n_each=3)
    first = run_pca(spectra, n_components=2)
    second = run_pca(spectra, n_components=2)

    assert first.scores == second.scores
    assert first.loadings == second.loadings


def test_pca_propagates_incompatible_spectra():
    low = _material((500.0,), lo=400.0, hi=700.0)
    high = _material((1500.0,), lo=1200.0, hi=1800.0)

    with pytest.raises(IncompatibleSpectraError):
        run_pca([low, high])


# ---------------------------------------------------------------------- HCA


def test_hca_returns_a_well_formed_tree():
    result = run_hca(_two_groups(n_each=3))

    assert result.n_spectra == 6
    # scipy's linkage matrix is always (N-1, 4).
    assert len(result.linkage_matrix) == 5
    assert all(len(row) == 4 for row in result.linkage_matrix)
    assert sorted(result.leaf_order) == list(range(6))


def test_hca_recovers_the_two_materials():
    result = run_hca(_two_groups(n_each=4), n_clusters=2)

    assert result.labels is not None
    group_a, group_b = set(result.labels[:4]), set(result.labels[4:])
    assert len(group_a) == 1 and len(group_b) == 1
    assert group_a != group_b


def test_correlation_metric_ignores_intensity_scale():
    """Same material at two laser powers must still cluster together —
    the reason correlation is the default metric."""
    base = _material((600.0, 1200.0), noise=0.5, seed=1)
    dim = (base[0], base[1] * 0.1)
    other = _material((900.0, 1500.0), noise=0.5, seed=2)

    result = run_hca([base, dim, other], metric="correlation", n_clusters=2)

    assert result.labels[0] == result.labels[1]
    assert result.labels[2] != result.labels[0]


def test_ward_with_non_euclidean_metric_is_rejected():
    """Ward is only defined for euclidean distance; scipy would otherwise
    produce a plot that quietly means nothing."""
    with pytest.raises(InvalidLinkageError, match="only defined for the euclidean"):
        run_hca(_two_groups(n_each=2), metric="correlation", method="ward")


def test_ward_with_euclidean_is_allowed():
    result = run_hca(_two_groups(n_each=2), metric="euclidean", method="ward")
    assert result.n_spectra == 4


def test_unknown_metric_and_method_are_rejected():
    with pytest.raises(InvalidLinkageError, match="Unknown distance metric"):
        run_hca(_two_groups(n_each=2), metric="nonsense")
    with pytest.raises(InvalidLinkageError, match="Unknown linkage method"):
        run_hca(_two_groups(n_each=2), method="nonsense")


def test_flat_spectrum_does_not_produce_a_nan_tree():
    """Correlation distance is undefined against a zero-variance spectrum;
    the tree must still come out finite rather than all-NaN."""
    flat = (np.linspace(400.0, 1800.0, 400), np.zeros(400))
    spectra = [*_two_groups(n_each=2), flat]

    result = run_hca(spectra, metric="correlation")

    assert np.all(np.isfinite(np.asarray(result.linkage_matrix)))
