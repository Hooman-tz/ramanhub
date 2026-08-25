#!/usr/bin/env python
"""Verify the OpenRouter setup end to end, against the live API.

Run from the repo root:

    make check-llm                 # list Qwen/flash models, then test the
                                   # configured one on a real vendor header
    make check-llm ARGS='--list'   # just list matching models
    make check-llm ARGS='--model qwen/qwen3-flash'   # try a specific slug

Why this exists: model slugs change, and a wrong one fails at runtime inside
a background ingestion job where nobody sees it. This asks OpenRouter what it
actually serves, then does one real forced tool call with the same code path
the parser uses — so "the parser works" is something you observe rather than
assume.

Never prints the API key.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import httpx
from app.config import settings
from app.ingestion.jobs import _extract_header_text
from app.ingestion.llm_fallback import (
    _SYSTEM_PROMPT,
    _TOOL_DESCRIPTION,
    _TOOL_INPUT_SCHEMA,
    _TOOL_NAME,
)
from app.ingestion.llm_providers import (
    LLMProviderError,
    OpenRouterProvider,
)
from app.schemas.ingestion import ExtractedMetadata

SAMPLE = (
    Path(__file__).resolve().parent.parent / "sample-data" / "horiba_acetaminophen_785nm.txt"
)


def list_models(needles: list[str]) -> list[dict]:
    """Ask OpenRouter what it actually serves. This is the authoritative
    answer — do not trust a slug written down anywhere, including here."""
    resp = httpx.get(
        f"{settings.OPENROUTER_BASE_URL}/models",
        headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
        timeout=30,
    )
    resp.raise_for_status()
    models = resp.json().get("data", [])
    hits = [
        m for m in models if any(n.lower() in m.get("id", "").lower() for n in needles)
    ]
    return sorted(hits, key=lambda m: m.get("id", ""))


def supports_tools(model: dict) -> bool:
    params = model.get("supported_parameters") or []
    return "tools" in params or "tool_choice" in params


def price_per_mtok(model: dict) -> str:
    pricing = model.get("pricing") or {}
    try:
        prompt = float(pricing.get("prompt", 0)) * 1_000_000
        completion = float(pricing.get("completion", 0)) * 1_000_000
    except (TypeError, ValueError):
        return "?"
    return f"${prompt:.3f}/${completion:.3f}"


def cmd_list(needles: list[str]) -> None:
    hits = list_models(needles)
    if not hits:
        print(f"No models matched {needles}.")
        return
    print(f"{len(hits)} model(s) matching {needles}\n")
    print(f"{'slug':<50} {'tools':<7} {'ctx':>9}  in/out $ per Mtok")
    print("-" * 92)
    for m in hits:
        mark = "yes" if supports_tools(m) else "NO"
        print(
            f"{m.get('id',''):<50} {mark:<7} {m.get('context_length', 0):>9}  "
            f"{price_per_mtok(m)}"
        )
    usable = [m for m in hits if supports_tools(m)]
    print(
        f"\n{len(usable)} of these support tool calling — only those can be used "
        "for header extraction."
    )
    if usable:
        cheapest = min(
            usable, key=lambda m: float((m.get("pricing") or {}).get("prompt", 1) or 1)
        )
        print(f"Cheapest tool-capable match: {cheapest.get('id')}")


async def cmd_test(model: str | None) -> int:
    if not SAMPLE.exists():
        print(f"Missing sample file: {SAMPLE}")
        return 1

    header = _extract_header_text(SAMPLE.read_bytes())
    raw_bytes = len(SAMPLE.read_bytes())
    print(f"Sample:  {SAMPLE.name}  ({raw_bytes:,} bytes on disk)")
    print(f"Header:  {len(header)} chars / {len(header.splitlines())} lines "
          f"(~{max(len(header)//4,1)} tokens sent, vs ~{raw_bytes//4:,} untrimmed)")
    print(f"Model:   {model or settings.OPENROUTER_MODEL}")
    print(f"Fallbacks: {settings.OPENROUTER_FALLBACK_MODELS}\n")

    provider = OpenRouterProvider(model_id=model) if model else OpenRouterProvider()
    try:
        payload = await provider.call_tool(
            system=_SYSTEM_PROMPT,
            user_text=f"Raw header text:\n\n{header}",
            tool_name=_TOOL_NAME,
            tool_description=_TOOL_DESCRIPTION,
            tool_schema=_TOOL_INPUT_SCHEMA,
            validate=lambda p: ExtractedMetadata.model_validate(p),
        )
    except LLMProviderError as exc:
        print(f"FAILED: {exc}")
        print("\nIf that says the model is unknown, run `make check-llm ARGS='--list'`")
        print("to see the slugs OpenRouter actually serves right now.")
        return 1

    metadata = ExtractedMetadata.model_validate(payload)
    print("Extracted and schema-validated:\n")
    print(json.dumps(metadata.model_dump(mode="json"), indent=2))

    # The header states these, so they are checkable rather than vibes.
    expected = {
        "laser_wavelength_nm": 785.0,
        "accumulations": 3,
        "grating_lines_mm": 1800.0,
    }
    print("\nAgainst what the header actually says:")
    ok = True
    for field, want in expected.items():
        got = getattr(metadata, field, None)
        hit = got == want
        ok = ok and hit
        print(f"  {'OK  ' if hit else 'MISS'} {field}: expected {want}, got {got}")
    print("\nPASS — parser is working." if ok else "\nModel ran but got fields wrong; try another slug.")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="only list matching models")
    parser.add_argument("--model", help="test a specific slug instead of the configured one")
    parser.add_argument(
        "--match", default="qwen,flash", help="comma-separated substrings for --list"
    )
    args = parser.parse_args()

    if not settings.OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY is not set (OPENROUTER is accepted as an alias).")
        return 1
    print(f"Key loaded: yes ({len(settings.OPENROUTER_API_KEY)} chars, value not shown)\n")

    needles = [n.strip() for n in args.match.split(",") if n.strip()]
    try:
        cmd_list(needles)
    except httpx.HTTPError as exc:
        print(f"Could not list models: {exc}")
        return 1

    if args.list:
        return 0
    print("\n" + "=" * 92 + "\n")
    return asyncio.run(cmd_test(args.model))


if __name__ == "__main__":
    raise SystemExit(main())
