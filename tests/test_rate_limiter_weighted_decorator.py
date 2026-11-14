"""Tests for weighted rate limiting through the @resilient decorator."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from pyresilience import (
    CacheConfig,
    EventType,
    FallbackConfig,
    RateLimit,
    RateLimiter,
    RateLimiterConfig,
    RateLimitExceededError,
    RateLimitFeedback,
    ResilienceEvent,
    RetryConfig,
    resilient,
)

# A long period keeps refill negligible, so levels are deterministic.
LONG = 3600.0


def _tokens_config(**kwargs: Any) -> RateLimiterConfig:
    """10 calls and 100 tokens per hour; a call costs len(prompt) tokens."""
    return RateLimiterConfig(
        max_calls=10,
        period=LONG,
        limits=[RateLimit(100, LONG, name="tokens", cost=lambda prompt="": len(prompt))],
        **kwargs,
    )


class TestWeightedLimiterDecoratorSync:
    def test_token_limit_rejects_and_names_the_limit(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(rate_limiter=_tokens_config(), listeners=[events.append])
        def complete(prompt: str) -> str:
            return prompt.upper()

        assert complete("x" * 80) == "X" * 80
        with pytest.raises(RateLimitExceededError, match="tokens"):
            complete("x" * 30)

        limited = [e for e in events if e.event_type == EventType.RATE_LIMITED]
        assert len(limited) == 1
        assert limited[0].detail == "limit 'tokens' exceeded"

    def test_rejection_without_listeners(self) -> None:
        @resilient(rate_limiter=_tokens_config())
        def complete(prompt: str) -> str:
            return prompt

        with pytest.raises(RateLimitExceededError, match="tokens"):
            complete("x" * 300)

    def test_fallback_on_rejection(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            rate_limiter=_tokens_config(),
            fallback=FallbackConfig(handler=lambda exc: f"fallback: {exc}"),
            listeners=[events.append],
        )
        def complete(prompt: str) -> str:
            return prompt

        assert complete("x" * 300) == "fallback: Rate limit exceeded (tokens)"
        assert [e.event_type for e in events] == [EventType.RATE_LIMITED, EventType.FALLBACK_USED]

    def test_fallback_on_rejection_without_listeners(self) -> None:
        @resilient(rate_limiter=_tokens_config(), fallback=FallbackConfig(handler="busy"))
        def complete(prompt: str) -> str:
            return prompt

        assert complete("x" * 300) == "busy"

    def test_plain_config_keeps_the_plain_limiter(self) -> None:
        @resilient(rate_limiter=RateLimiterConfig(max_calls=5, period=1.0))
        def call() -> str:
            return "ok"

        executor = call._executor  # type: ignore[attr-defined]
        assert isinstance(executor._rate_limiter, RateLimiter)
        assert executor._weighted_limiter is None

    def test_reconcile_through_the_decorator(self) -> None:
        config = RateLimiterConfig(
            max_calls=10,
            period=LONG,
            limits=[
                RateLimit(
                    1000,
                    LONG,
                    name="tokens",
                    cost=lambda prompt: 500,
                    actual_cost=lambda response: response["usage"],
                )
            ],
        )

        @resilient(rate_limiter=config)
        def complete(prompt: str) -> dict[str, Any]:
            return {"text": "hi", "usage": 120}

        complete("hello")
        levels = complete._executor._weighted_limiter.levels()  # type: ignore[attr-defined]
        assert levels["tokens"] == pytest.approx(880.0, abs=1.0)

    def test_retries_are_charged_when_asked(self) -> None:
        attempts = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG, charge_retries=True),
        )
        def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ValueError("not yet")
            return "ok"

        assert flaky() == "ok"
        levels = flaky._executor._weighted_limiter.levels()  # type: ignore[attr-defined]
        assert levels["calls"] == pytest.approx(7.0, abs=0.01)

    def test_server_feedback_pauses_following_calls(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            rate_limiter=RateLimiterConfig(
                max_calls=10,
                period=LONG,
                feedback=lambda outcome: (
                    RateLimitFeedback(retry_after=30.0) if outcome == "throttled" else None
                ),
            ),
            listeners=[events.append],
        )
        def call(answer: str) -> str:
            return answer

        assert call("fine") == "fine"
        assert call("throttled") == "throttled"
        with pytest.raises(RateLimitExceededError, match="server feedback"):
            call("fine")
        limited = [e for e in events if e.event_type == EventType.RATE_LIMITED]
        assert limited[0].detail == "limit 'server feedback' exceeded"

    def test_cache_hit_consumes_nothing(self) -> None:
        @resilient(rate_limiter=_tokens_config(), cache=CacheConfig(max_size=8, ttl=60.0))
        def complete(prompt: str) -> str:
            return prompt.upper()

        complete("x" * 60)
        complete("x" * 60)  # served from the cache
        levels = complete._executor._weighted_limiter.levels()  # type: ignore[attr-defined]
        assert levels["calls"] == pytest.approx(9.0, abs=0.01)
        assert levels["tokens"] == pytest.approx(40.0, abs=0.1)


class TestWeightedLimiterDecoratorAsync:
    async def test_token_limit_rejects_and_names_the_limit(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(rate_limiter=_tokens_config(), listeners=[events.append])
        async def complete(prompt: str) -> str:
            return prompt.upper()

        assert await complete("x" * 80) == "X" * 80
        with pytest.raises(RateLimitExceededError, match="tokens"):
            await complete("x" * 30)

        limited = [e for e in events if e.event_type == EventType.RATE_LIMITED]
        assert len(limited) == 1
        assert limited[0].detail == "limit 'tokens' exceeded"

    async def test_rejection_without_listeners(self) -> None:
        @resilient(rate_limiter=_tokens_config())
        async def complete(prompt: str) -> str:
            return prompt

        with pytest.raises(RateLimitExceededError, match="tokens"):
            await complete("x" * 300)

    async def test_fallback_on_rejection(self) -> None:
        events: list[ResilienceEvent] = []

        async def handler(exc: BaseException) -> str:
            return f"fallback: {exc}"

        @resilient(
            rate_limiter=_tokens_config(),
            fallback=FallbackConfig(handler=handler),
            listeners=[events.append],
        )
        async def complete(prompt: str) -> str:
            return prompt

        assert await complete("x" * 300) == "fallback: Rate limit exceeded (tokens)"
        assert [e.event_type for e in events] == [EventType.RATE_LIMITED, EventType.FALLBACK_USED]

    async def test_fallback_on_rejection_without_listeners(self) -> None:
        @resilient(rate_limiter=_tokens_config(), fallback=FallbackConfig(handler="busy"))
        async def complete(prompt: str) -> str:
            return prompt

        assert await complete("x" * 300) == "busy"

    async def test_reconcile_through_the_decorator(self) -> None:
        config = RateLimiterConfig(
            max_calls=10,
            period=LONG,
            limits=[
                RateLimit(
                    1000,
                    LONG,
                    name="tokens",
                    cost=lambda prompt: 500,
                    actual_cost=lambda response: response["usage"],
                )
            ],
        )

        @resilient(rate_limiter=config)
        async def complete(prompt: str) -> dict[str, Any]:
            return {"text": "hi", "usage": 120}

        await complete("hello")
        levels = complete._executor._weighted_limiter.levels()  # type: ignore[attr-defined]
        assert levels["tokens"] == pytest.approx(880.0, abs=1.0)

    async def test_retries_are_charged_when_asked(self) -> None:
        attempts = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG, charge_retries=True),
        )
        async def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ValueError("not yet")
            return "ok"

        assert await flaky() == "ok"
        levels = flaky._executor._weighted_limiter.levels()  # type: ignore[attr-defined]
        assert levels["calls"] == pytest.approx(7.0, abs=0.01)

    async def test_server_feedback_pauses_following_calls(self) -> None:
        @resilient(
            rate_limiter=RateLimiterConfig(
                max_calls=10,
                period=LONG,
                feedback=lambda outcome: (
                    RateLimitFeedback(retry_after=30.0) if outcome == "throttled" else None
                ),
            ),
        )
        async def call(answer: str) -> str:
            return answer

        assert await call("throttled") == "throttled"
        with pytest.raises(RateLimitExceededError, match="server feedback"):
            await call("fine")

    async def test_concurrent_calls_respect_the_token_limit(self) -> None:
        @resilient(rate_limiter=_tokens_config())
        async def complete(prompt: str) -> str:
            await asyncio.sleep(0.01)
            return prompt

        results = await asyncio.gather(
            *(complete("x" * 30) for _ in range(6)), return_exceptions=True
        )
        passed = [r for r in results if isinstance(r, str)]
        rejected = [r for r in results if isinstance(r, RateLimitExceededError)]
        # 100 tokens allow three 30-token calls
        assert len(passed) == 3
        assert len(rejected) == 3
