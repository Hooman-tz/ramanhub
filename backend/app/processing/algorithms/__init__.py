"""Pure, versioned processing algorithms.

Each module exposes `apply(spectrum: np.ndarray, **params) -> np.ndarray` and
a module-level `VERSION` string. `registry.py` maps namespaced step types
(e.g. "raman.snv") to `(callable, version)` pairs.
"""
