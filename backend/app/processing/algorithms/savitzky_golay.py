"""Savitzky-Golay smoothing (and optional derivative).

Fits a low-order polynomial to a sliding window by least squares and takes
that polynomial's value (or `deriv`-th derivative) at the window centre.
Unlike a moving average, it preserves peak height and width, which is why
it's the standard smoother for spectroscopy — a moving average of the same
width visibly flattens sharp Raman bands.

`deriv=1` / `deriv=2` are exposed because derivative spectra are a common
Raman preprocessing choice in their own right: differentiating removes an
additive (1st) or additive-plus-linear (2nd) background while sharpening
overlapping bands.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter

STEP_TYPE = "raman.smooth.savitzky_golay"
VERSION = "1.0.0"
LABEL = "Savitzky-Golay smoothing"
CATEGORY = "smoothing"
DESCRIPTION = (
    "Sliding-window polynomial smoothing that preserves peak height and width, with "
    "optional 1st/2nd derivative output."
)
PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "window_length": {
            "type": "integer",
            "default": 9,
            "minimum": 3,
            "title": "Window length (points)",
            "description": "Must be odd and greater than polyorder. Wider means smoother, "
            "at the cost of blurring narrow bands.",
        },
        "polyorder": {
            "type": "integer",
            "default": 3,
            "minimum": 0,
            "title": "Polynomial order",
        },
        "deriv": {
            "type": "integer",
            "default": 0,
            "minimum": 0,
            "title": "Derivative order",
            "description": "0 smooths; 1 and 2 return the corresponding derivative spectrum.",
        },
    },
}


def apply(spectrum: np.ndarray, **params) -> np.ndarray:
    window_length = int(params.get("window_length", 9))
    polyorder = int(params.get("polyorder", 3))
    deriv = int(params.get("deriv", 0))

    x = np.asarray(spectrum, dtype=float)
    if window_length % 2 == 0:
        raise ValueError(
            f"savitzky_golay: window_length must be odd, got {window_length}"
        )
    if window_length <= polyorder:
        raise ValueError(
            f"savitzky_golay: window_length ({window_length}) must be greater than "
            f"polyorder ({polyorder})"
        )
    if window_length > x.size:
        raise ValueError(
            f"savitzky_golay: window_length ({window_length}) exceeds the spectrum "
            f"length ({x.size})"
        )
    return np.asarray(savgol_filter(x, window_length, polyorder, deriv=deriv))
