"""Tests for rate limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from pyresilience._rate_limiter import AsyncRateLimiter, RateLimiter, RateLimitExceededError
from pyresilience._types import RateLimiterConfig


class TestRateLimiter:
    def test_allows_calls_within_limit(self) -> None:
        config = RateLimiterConfig(max_calls=5, period=1.0)
        rl = RateLimiter(config)
        for _ in range(5):
            assert rl.acquire() is True

    def test_rejects_calls_over_limit(self) -> None:
        config = RateLimiterConfig(max_calls=2, period=1.0, max_wait=0)
        rl = RateLimiter(config)
        assert rl.acquire() is True
        assert rl.acquire() is True
        assert rl.acquire() is False

    def test_tokens_refill_over_time(self) -> None:
        config = RateLimiterConfig(max_calls=2, period=0.1)
        rl = RateLimiter(config)
        assert rl.acquire() is True
        assert rl.acquire() is True
        assert rl.acquire() is False
        time.sleep(0.15)
        assert rl.acquire() is True

    def test_max_wait_waits_for_token(self) -> None:
        config = RateLimiterConfig(max_calls=1, period=0.05, max_wait=0.2)
        rl = RateLimiter(config)
        assert rl.acquire() is True
        # Should wait and succeed
        assert rl.acquire() is True

    def test_max_wait_timeout(self) -> None:
        config = RateLimiterConfig(max_calls=1, period=10.0, max_wait=0.05)
        rl = RateLimiter(config)
        assert rl.acquire() is True
        assert rl.acquire() is False

    def test_reset(self) -> None:
        config = RateLimiterConfig(max_calls=1, period=10.0)
        rl = RateLimiter(config)
        assert rl.acquire() is True
        assert rl.acquire() is False
        rl.reset()
        assert rl.acquire() is True

    def test_rate_limit_exceeded_error(self) -> None:
        exc = RateLimitExceededError("test")
        assert str(exc) == "test"
        assert isinstance(exc, Exception)


class TestAsyncRateLimiter:
    async def test_allows_calls_within_limit(self) -> None:
        config = RateLimiterConfig(max_calls=5, period=1.0)
        rl = AsyncRateLimiter(config)
        for _ in range(5):
            assert await rl.acquire() is True

    async def test_rejects_calls_over_limit(self) -> None:
        config = RateLimiterConfig(max_calls=2, period=1.0, max_wait=0)
        rl = AsyncRateLimiter(config)
        assert await rl.acquire() is True
        assert await rl.acquire() is True
        assert await rl.acquire() is False

    async def test_tokens_refill_over_time(self) -> None:
        config = RateLimiterConfig(max_calls=2, period=0.1)
        rl = AsyncRateLimiter(config)
        assert await rl.acquire() is True
        assert await rl.acquire() is True
        assert await rl.acquire() is False
        await asyncio.sleep(0.15)
        assert await rl.acquire() is True

    async def test_max_wait_waits_for_token(self) -> None:
        config = RateLimiterConfig(max_calls=1, period=0.05, max_wait=0.2)
        rl = AsyncRateLimiter(config)
        assert await rl.acquire() is True
        assert await rl.acquire() is True

    async def test_reset(self) -> None:
        config = RateLimiterConfig(max_calls=1, period=10.0)
        rl = AsyncRateLimiter(config)
        assert await rl.acquire() is True
        assert await rl.acquire() is False
        rl.reset()
        assert await rl.acquire() is True


class TestRateLimiterIntegration:
    def test_sync_decorator_rate_limited(self) -> None:
        from pyresilience import RateLimiterConfig, resilient

        @resilient(rate_limiter=RateLimiterConfig(max_calls=2, period=1.0, max_wait=0))
        def my_func() -> str:
            return "ok"

        assert my_func() == "ok"
        assert my_func() == "ok"
        with pytest.raises(RateLimitExceededError):
            my_func()

    async def test_async_decorator_rate_limited(self) -> None:
        from pyresilience import RateLimiterConfig, resilient

        @resilient(rate_limiter=RateLimiterConfig(max_calls=2, period=1.0, max_wait=0))
        async def my_func() -> str:
            return "ok"

        assert await my_func() == "ok"
        assert await my_func() == "ok"
        with pytest.raises(RateLimitExceededError):
            await my_func()

    def test_rate_limited_with_fallback(self) -> None:
        from pyresilience import FallbackConfig, RateLimiterConfig, resilient

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=1, period=1.0, max_wait=0),
            fallback=FallbackConfig(
                handler=lambda exc: "fallback",
                fallback_on=(RateLimitExceededError,),
            ),
        )
        def my_func() -> str:
            return "ok"

        assert my_func() == "ok"
        assert my_func() == "fallback"

    def test_rate_limit_event_emitted(self) -> None:
        from pyresilience import EventType, RateLimiterConfig, resilient
        from pyresilience._types import ResilienceEvent

        events: list[ResilienceEvent] = []

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=1, period=1.0, max_wait=0),
            listeners=[events.append],
        )
        def my_func() -> str:
            return "ok"

        my_func()
        with pytest.raises(RateLimitExceededError):
            my_func()

        event_types = [e.event_type for e in events]
        assert EventType.RATE_LIMITED in event_types
