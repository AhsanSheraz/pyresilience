"""Tests for rate limits shared between instances through a StateBackend."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import pytest

from pyresilience import (
    InMemoryBackend,
    RateLimit,
    RateLimiterConfig,
    RateLimitExceededError,
    ResilienceConfig,
    ResilienceRegistry,
    RetryConfig,
    SharedStateConfig,
    resilient,
)
from pyresilience._executor import _SyncExecutor

LONG = 3600.0


class BrokenBackend:
    """A backend that is unreachable."""

    def get(self, key: str) -> Optional[str]:
        raise ConnectionError("backend down")

    def set(self, key: str, value: str, ttl: Optional[float] = None) -> None:
        raise ConnectionError("backend down")

    def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float:
        raise ConnectionError("backend down")

    def delete(self, key: str) -> None:
        raise ConnectionError("backend down")


class TokensDownBackend(InMemoryBackend):
    """Counts calls fine but fails on the token counter."""

    undo_fails = False

    def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float:
        if ":tokens:" in key:
            raise ConnectionError("token counter down")
        if amount < 0 and self.undo_fails:
            raise ConnectionError("undo failed")
        return super().incr(key, amount, ttl)


def _shared(backend: Any, **kwargs: Any) -> SharedStateConfig:
    return SharedStateConfig(backend=backend, key="svc", sync_interval=0, **kwargs)


def _end_pause(call: Any) -> None:
    """Let the next call try a failed backend again without waiting for the pause."""
    call._executor._weighted_limiter._core.shared._down_until = time.monotonic() - 0.001


def _counter(backend: InMemoryBackend, limit: str) -> float:
    """Value of the current shared window of a limit (0.0 when absent)."""
    names = backend.keys()
    for key in names:
        if key.startswith(f"svc:rl:{limit}:"):
            return float(backend.get(key) or 0.0)
    return 0.0


def _tokens_limiter(**kwargs: Any) -> RateLimiterConfig:
    return RateLimiterConfig(
        max_calls=10,
        period=LONG,
        limits=[RateLimit(100, LONG, name="tokens", cost=lambda prompt: len(prompt))],
        **kwargs,
    )


class TestSharedRateLimitSync:
    def test_limit_holds_across_instances(self) -> None:
        backend = InMemoryBackend()
        limiter = RateLimiterConfig(max_calls=3, period=LONG)

        @resilient(rate_limiter=limiter, shared_state=_shared(backend))
        def a() -> str:
            return "a"

        @resilient(rate_limiter=limiter, shared_state=_shared(backend))
        def b() -> str:
            return "b"

        assert a() == "a"
        assert a() == "a"
        assert b() == "b"
        # b made one call only, but the shared limit of 3 is used up
        with pytest.raises(RateLimitExceededError, match="calls"):
            b()
        # The rejected call was taken back from the shared window
        assert _counter(backend, "calls") == 3.0
        # ...and from b's local bucket
        levels = b._executor._weighted_limiter.levels()  # type: ignore[attr-defined]
        assert levels["calls"] == pytest.approx(2.0, abs=0.01)

    def test_weighted_limits_are_shared_all_or_nothing(self) -> None:
        backend = InMemoryBackend()

        @resilient(rate_limiter=_tokens_limiter(), shared_state=_shared(backend))
        def a(prompt: str) -> str:
            return prompt

        @resilient(rate_limiter=_tokens_limiter(), shared_state=_shared(backend))
        def b(prompt: str) -> str:
            return prompt

        a("x" * 60)
        with pytest.raises(RateLimitExceededError, match="tokens"):
            b("x" * 60)
        # b's call was undone on both shared limits
        assert _counter(backend, "calls") == 1.0
        assert _counter(backend, "tokens") == 60.0

    def test_reconcile_corrects_the_shared_window(self) -> None:
        backend = InMemoryBackend()
        limiter = RateLimiterConfig(
            max_calls=10,
            period=LONG,
            limits=[
                RateLimit(
                    100,
                    LONG,
                    name="tokens",
                    cost=lambda: 50,
                    actual_cost=lambda result: result,
                )
            ],
        )

        @resilient(rate_limiter=limiter, shared_state=_shared(backend))
        def call() -> int:
            return 20

        call()
        assert _counter(backend, "tokens") == 20.0

    def test_charged_retries_reach_the_shared_window(self) -> None:
        backend = InMemoryBackend()
        attempts = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG, charge_retries=True),
            shared_state=_shared(backend),
        )
        def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("not yet")
            return "ok"

        assert flaky() == "ok"
        assert _counter(backend, "calls") == 3.0

    def test_waits_for_the_next_shared_window(self) -> None:
        backend = InMemoryBackend()
        limiter = RateLimiterConfig(max_calls=1, period=0.3, max_wait=3.0)

        @resilient(rate_limiter=limiter, shared_state=_shared(backend))
        def a() -> str:
            return "a"

        @resilient(rate_limiter=limiter, shared_state=_shared(backend))
        def b() -> str:
            return "b"

        assert a() == "a"
        start = time.monotonic()
        assert b() == "b"  # waits until the 0.3s window rolls over
        assert time.monotonic() - start < 2.0

    def test_different_keys_do_not_share(self) -> None:
        backend = InMemoryBackend()
        limiter = RateLimiterConfig(max_calls=1, period=LONG)

        @resilient(
            rate_limiter=limiter,
            shared_state=SharedStateConfig(backend=backend, key="one", sync_interval=0),
        )
        def a() -> str:
            return "a"

        @resilient(
            rate_limiter=limiter,
            shared_state=SharedStateConfig(backend=backend, key="two", sync_interval=0),
        )
        def b() -> str:
            return "b"

        assert a() == "a"
        assert b() == "b"

    def test_default_key_is_the_function_path(self) -> None:
        backend = InMemoryBackend()

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=5, period=LONG),
            shared_state=SharedStateConfig(backend=backend, sync_interval=0),
        )
        def my_function() -> str:
            return "ok"

        my_function()
        (key,) = backend.keys()
        assert "test_default_key_is_the_function_path.<locals>.my_function:rl:calls:" in key
        assert key.startswith(__name__)

    def test_registry_name_is_the_default_key(self) -> None:
        backend = InMemoryBackend()
        registry = ResilienceRegistry()
        registry.register(
            "payments",
            ResilienceConfig(
                rate_limiter=RateLimiterConfig(max_calls=5, period=LONG),
                shared_state=SharedStateConfig(backend=backend, sync_interval=0),
            ),
        )

        @registry.decorator("payments")
        def charge() -> str:
            return "ok"

        charge()
        (key,) = backend.keys()
        assert key.startswith("payments:rl:calls:")

    def test_missing_key_is_an_error(self) -> None:
        config = ResilienceConfig(
            rate_limiter=RateLimiterConfig(),
            shared_state=SharedStateConfig(backend=InMemoryBackend(), sync_interval=0),
        )
        with pytest.raises(ValueError, match="shared_state needs a key"):
            _SyncExecutor(config)


class TestSharedRateLimitBackendFailure:
    def test_fail_open_keeps_serving_on_the_local_limit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        limiter = RateLimiterConfig(max_calls=2, period=LONG)

        @resilient(rate_limiter=limiter, shared_state=_shared(BrokenBackend()))
        def call() -> str:
            return "ok"

        with caplog.at_level(logging.DEBUG, logger="pyresilience"):
            assert call() == "ok"
            _end_pause(call)
            assert call() == "ok"
            # The local limit still applies
            with pytest.raises(RateLimitExceededError, match="calls"):
                call()

        levels = [record.levelno for record in caplog.records]
        # The first failure of the outage is a warning, the next one is quiet
        assert levels == [logging.WARNING, logging.DEBUG]

    def test_fail_closed_rejects_calls(self) -> None:
        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=5, period=LONG, max_wait=5.0),
            shared_state=_shared(BrokenBackend(), fail_open=False),
        )
        def call() -> str:
            return "ok"

        start = time.monotonic()
        with pytest.raises(RateLimitExceededError, match="state backend unavailable"):
            call()
        # Rejected at once: waiting cannot fix an unreachable backend
        assert time.monotonic() - start < 1.0

    def test_partial_failure_is_undone(self) -> None:
        backend = TokensDownBackend()

        @resilient(rate_limiter=_tokens_limiter(), shared_state=_shared(backend))
        def call(prompt: str) -> str:
            return prompt

        assert call("x" * 10) == "x" * 10  # fail-open
        assert _counter(backend, "calls") == 0.0

    def test_failed_undo_is_tolerated(self) -> None:
        backend = TokensDownBackend()
        backend.undo_fails = True

        @resilient(rate_limiter=_tokens_limiter(), shared_state=_shared(backend))
        def call(prompt: str) -> str:
            return prompt

        assert call("x" * 10) == "x" * 10
        assert _counter(backend, "calls") == 1.0

    def test_failed_correction_never_breaks_the_call(self) -> None:
        class NoCorrections(InMemoryBackend):
            def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float:
                if amount < 0:
                    raise ConnectionError("backend down")
                return super().incr(key, amount, ttl)

        limiter = RateLimiterConfig(
            max_calls=10, period=LONG, cost=lambda: 5, actual_cost=lambda result: 1
        )

        @resilient(rate_limiter=limiter, shared_state=_shared(NoCorrections()))
        def call() -> str:
            return "ok"

        assert call() == "ok"

    def test_backend_recovery_is_noticed(self, caplog: pytest.LogCaptureFixture) -> None:
        class Flaky(InMemoryBackend):
            down = True

            def incr(self, key: str, amount: float, ttl: Optional[float] = None) -> float:
                if self.down:
                    raise ConnectionError("backend down")
                return super().incr(key, amount, ttl)

        backend = Flaky()

        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG),
            shared_state=_shared(backend),
        )
        def call() -> str:
            return "ok"

        with caplog.at_level(logging.WARNING, logger="pyresilience"):
            call()
            backend.down = False
            _end_pause(call)
            call()
            backend.down = True
            call()
        # Each outage is announced once, also after a recovery in between
        assert len(caplog.records) == 2


class TestSharedRateLimitAsync:
    async def test_limit_holds_across_sync_and_async_instances(self) -> None:
        backend = InMemoryBackend()
        limiter = RateLimiterConfig(max_calls=2, period=LONG)

        @resilient(rate_limiter=limiter, shared_state=_shared(backend))
        def sync_call() -> str:
            return "sync"

        @resilient(rate_limiter=limiter, shared_state=_shared(backend))
        async def async_call() -> str:
            return "async"

        assert sync_call() == "sync"
        assert await async_call() == "async"
        with pytest.raises(RateLimitExceededError, match="calls"):
            await async_call()
        assert _counter(backend, "calls") == 2.0

    async def test_reconcile_corrects_the_shared_window(self) -> None:
        backend = InMemoryBackend()
        limiter = RateLimiterConfig(
            max_calls=10,
            period=LONG,
            limits=[
                RateLimit(
                    100,
                    LONG,
                    name="tokens",
                    cost=lambda: 50,
                    actual_cost=lambda result: result,
                )
            ],
        )

        @resilient(rate_limiter=limiter, shared_state=_shared(backend))
        async def call() -> int:
            return 20

        await call()
        assert _counter(backend, "tokens") == 20.0

    async def test_charged_retries_reach_the_shared_window(self) -> None:
        backend = InMemoryBackend()
        attempts = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            rate_limiter=RateLimiterConfig(max_calls=10, period=LONG, charge_retries=True),
            shared_state=_shared(backend),
        )
        async def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("not yet")
            return "ok"

        assert await flaky() == "ok"
        assert _counter(backend, "calls") == 3.0

    async def test_fail_closed_rejects_calls(self) -> None:
        @resilient(
            rate_limiter=RateLimiterConfig(max_calls=5, period=LONG),
            shared_state=_shared(BrokenBackend(), fail_open=False),
        )
        async def call() -> str:
            return "ok"

        with pytest.raises(RateLimitExceededError, match="state backend unavailable"):
            await call()
