from __future__ import annotations

import asyncio

import pytest

from app.ingestion.jobs import LeaseLostError, await_with_lease_heartbeats


def test_async_extraction_renews_the_lease_while_waiting():
    heartbeats: list[bool] = []

    async def slow_result():
        await asyncio.sleep(0.03)
        return "metadata"

    result = asyncio.run(
        await_with_lease_heartbeats(
            slow_result(),
            on_heartbeat=lambda: heartbeats.append(True) or True,
            timeout=1,
            heartbeat_interval=0.005,
        )
    )

    assert result == "metadata"
    assert heartbeats


def test_async_extraction_cancels_when_lease_is_lost():
    async def slow_result():
        await asyncio.sleep(1)
        return "metadata"

    with pytest.raises(LeaseLostError):
        asyncio.run(
            await_with_lease_heartbeats(
                slow_result(),
                on_heartbeat=lambda: False,
                timeout=1,
                heartbeat_interval=0.005,
            )
        )