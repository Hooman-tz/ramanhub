"""Deterministic, regex-based filename metadata overlay.

Raman export filenames very often encode acquisition facts the vendor header
omits, e.g. ``polystyrene_532nm_10s_x50.txt``. This module extracts those
facts with plain regexes (no LLM, no network) and uses them to fill *only*
fields a real parser or the LLM fallback left ``None``.

Hard rules enforced here:

* **Never overwrite a value that came from the file itself.** ``apply`` only
  writes a field when the incoming ``ExtractedMetadata`` has ``None`` there.
* **Guard the wavelength / wavenumber confusion.** A laser excitation
  wavelength is in nanometres and realistically 200-1100 nm. A token like
  ``3200`` (a Raman-shift range endpoint) or ``1800`` (grating lines/mm)
  must never land in ``laser_wavelength_nm``; anything outside
  ``[LASER_NM_MIN, LASER_NM_MAX]`` is dropped.

The overlay is intentionally conservative: it works token-by-token on the
filename stem (split on ``_``, ``-``, whitespace and dots) and only accepts
tokens that *fully* match a pattern, so a stray number in the name cannot be
mistaken for a measurement.
"""
from __future__ import annotations

import os
import re

from app.schemas.ingestion import ExtractedMetadata

# Physical bounds for an excitation laser wavelength, in nm. Shared with the
# LLM fallback's own backstop (`llm_fallback._LASER_NM_MIN/_MAX`).
LASER_NM_MIN = 200.0
LASER_NM_MAX = 1100.0

# Plausible bounds for a microscope objective magnification.
_OBJECTIVE_MIN = 1.0
_OBJECTIVE_MAX = 250.0

# Plausible upper bound for an integration/exposure time expressed in the
# filename in seconds (24h). Lower bound is > 0.
_MAX_INTEGRATION_SECONDS = 86_400.0

# Plausible upper bound for a laser power quoted in mW in a filename.
_MAX_LASER_POWER_MW = 100_000.0

_TOKEN_SPLIT_RE = re.compile(r"[\s_\-.]+")

# `(\d{3,4}) nm` — laser excitation wavelength. Range-checked after parsing.
_WAVELENGTH_RE = re.compile(r"^(\d{3,4})\s?nm$", re.IGNORECASE)

# `x(\d+)` and the equally common `(\d+)x` — objective magnification.
_OBJECTIVE_RE = re.compile(r"^(?:x(\d{1,3})|(\d{1,3})x)$", re.IGNORECASE)

# `(\d+)s` / `(\d+)sec` — integration time in seconds.
_INTEGRATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s?s(?:ec)?$", re.IGNORECASE)

# `(\d+)mW` — laser power.
_LASER_POWER_RE = re.compile(r"^(\d+(?:\.\d+)?)\s?mw$", re.IGNORECASE)

# `(\d+)x` accumulations are ambiguous with objective, so accumulations are
# only read from an explicit `(\d+)acc` / `(\d+)accum` token.
_ACCUMULATIONS_RE = re.compile(r"^(\d{1,4})\s?accum?(?:ulations?)?$", re.IGNORECASE)

# Recognisable Raman reference / sample materials. Matched as a whole token
# (case-insensitively), or as a token that is the material name followed only
# by digits (``polystyrene1``). Keep the canonical spelling as the value
# written to ``sample_description``.
_MATERIALS: tuple[str, ...] = (
    "polystyrene",
    "polyethylene",
    "polypropylene",
    "pmma",
    "ptfe",
    "pet",
    "nylon",
    "cellulose",
    "silicon",
    "graphene",
    "graphite",
    "diamond",
    "quartz",
    "calcite",
    "aragonite",
    "gypsum",
    "sapphire",
    "sulfur",
    "sulphur",
    "titania",
    "anatase",
    "rutile",
    "hematite",
    "magnetite",
    "gold",
    "silver",
    "copper",
    "paracetamol",
    "acetaminophen",
    "aspirin",
    "ibuprofen",
    "caffeine",
    "glucose",
    "sucrose",
    "lactose",
    "ethanol",
    "methanol",
    "acetone",
    "toluene",
    "benzene",
    "water",
    "cyclohexane",
    "naphthalene",
    "mica",
    "kaolinite",
)


def _stem_tokens(filename: str) -> list[str]:
    stem = os.path.basename(filename)
    # Drop a single trailing extension only (keep e.g. "10s" intact).
    stem = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", stem)
    return [t for t in _TOKEN_SPLIT_RE.split(stem) if t]


def _laser_wavelength_nm(tokens: list[str]) -> float | None:
    for tok in tokens:
        m = _WAVELENGTH_RE.match(tok)
        if not m:
            continue
        value = float(m.group(1))
        # The wavelength/wavenumber guard: only 200-1100 nm is a real laser.
        if LASER_NM_MIN <= value <= LASER_NM_MAX:
            return value
    return None


def _objective(tokens: list[str]) -> float | None:
    for tok in tokens:
        m = _OBJECTIVE_RE.match(tok)
        if not m:
            continue
        raw = m.group(1) or m.group(2)
        value = float(raw)
        if _OBJECTIVE_MIN <= value <= _OBJECTIVE_MAX:
            return value
    return None


def _integration_time_ms(tokens: list[str]) -> float | None:
    for tok in tokens:
        m = _INTEGRATION_RE.match(tok)
        if not m:
            continue
        seconds = float(m.group(1))
        if 0.0 < seconds <= _MAX_INTEGRATION_SECONDS:
            return seconds * 1000.0
    return None


def _laser_power_mw(tokens: list[str]) -> float | None:
    for tok in tokens:
        m = _LASER_POWER_RE.match(tok)
        if not m:
            continue
        value = float(m.group(1))
        if 0.0 < value <= _MAX_LASER_POWER_MW:
            return value
    return None


def _accumulations(tokens: list[str]) -> int | None:
    for tok in tokens:
        m = _ACCUMULATIONS_RE.match(tok)
        if m:
            return int(m.group(1))
    return None


def _sample_description(tokens: list[str]) -> str | None:
    lowered = [t.lower() for t in tokens]
    for tok in lowered:
        for material in _MATERIALS:
            # whole token, or "<material><digits>" (e.g. "polystyrene1")
            if tok == material or (
                tok.startswith(material) and tok[len(material) :].isdigit()
            ):
                return material
    return None


def apply(metadata: ExtractedMetadata, filename: str | None) -> ExtractedMetadata:
    """Return ``metadata`` with null fields filled from ``filename`` hints.

    Never overwrites a non-null field. Returns the input unchanged when
    ``filename`` is empty or yields no usable hints.
    """
    if not filename:
        return metadata

    tokens = _stem_tokens(filename)
    if not tokens:
        return metadata

    updates: dict[str, object] = {}

    if metadata.laser_wavelength_nm is None:
        nm = _laser_wavelength_nm(tokens)
        if nm is not None:
            updates["laser_wavelength_nm"] = nm

    if metadata.objective_magnification is None:
        objective = _objective(tokens)
        if objective is not None:
            updates["objective_magnification"] = objective

    if metadata.integration_time_ms is None:
        integration = _integration_time_ms(tokens)
        if integration is not None:
            updates["integration_time_ms"] = integration

    if metadata.laser_power_mw is None:
        power = _laser_power_mw(tokens)
        if power is not None:
            updates["laser_power_mw"] = power

    if metadata.accumulations is None:
        accumulations = _accumulations(tokens)
        if accumulations is not None:
            updates["accumulations"] = accumulations

    if metadata.sample_description is None:
        description = _sample_description(tokens)
        if description is not None:
            updates["sample_description"] = description

    if not updates:
        return metadata
    return metadata.model_copy(update=updates)
