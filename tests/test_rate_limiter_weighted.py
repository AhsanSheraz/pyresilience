"""Tests for weighted, multi-limit rate limiting."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

import pytest

from pyresilience import (
    RateLimit,
    RateLimiterConfig,
    RateLimitFeedback,
)
from pyresilience._weighted_limiter import (
    _AsyncWeightedRateLimiter,
    _needs_weighted_limiter,
    _WeightedRateLimiter,
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


class TestRateLimitValidation:
    def test_max_units_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_units must be > 0"):
            RateLimit(max_units=0, period=1.0)

    def test_period_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="period must be > 0"):
            RateLimit(max_units=1, period=0)

    def test_limit_names_must_be_unique(self) -> None:
        with pytest.raises(ValueError, match="limit names must be unique"):
            RateLimiterConfig(limits=[RateLimit(1, 1.0, name="a"), RateLimit(1, 1.0, name="a")])

    def test_primary_limit_name_is_reserved(self) -> None:
        with pytest.raises(ValueError, match="limit names must be unique"):
            RateLimiterConfig(limits=[RateLimit(1, 1.0, name="calls")])

    def test_unnamed_limits_get_numbered_names(self) -> None:
        config = RateLimiterConfig(limits=[RateLimit(5, LONG), RateLimit(7, LONG)])
        limiter = _WeightedRateLimiter(config)
        assert limiter.levels() == {"calls": 10.0, "limit1": 5.0, "limit2": 7.0}

    def test_plain_config_does_not_need_the_weighted_limiter(self) -> None:
        assert _needs_weighted_limiter(RateLimiterConfig()) is False

    @pytest.mark.parametrize(
        "config",
        [
            RateLimiterConfig(cost=lambda: 2.0),
            RateLimiterConfig(actual_cost=lambda result: 1.0),
            RateLimiterConfig(limits=[RateLimit(1, 1.0)]),
            RateLimiterConfig(feedback=lambda outcome: None),
            RateLimiterConfig(charge_retries=True),
        ],
    )
    def test_advanced_options_select_the_weighted_limiter(self, config: RateLimiterConfig) -> None:
        assert _needs_weighted_limiter(config) is True


class TestWeightedRateLimiterSync:
    def test_weighted_cost_on_primary_limit(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=10, period=LONG, cost=lambda units: units)
        )
        costs, blocker = limiter.reserve((4,), {})
        assert costs == [4.0]
        assert blocker == ""
        assert limiter.levels()["calls"] == pytest.approx(6.0, abs=0.01)

        costs, blocker = limiter.reserve((7,), {})
        assert costs is None
        assert blocker == "calls"

    def test_cost_receives_keyword_arguments(self) -> None:
        limiter = _WeightedRateLimiter(_tokens_config())
        costs, _ = limiter.reserve((), {"prompt": "x" * 30})
        assert costs == [1.0, 30.0]

    def test_all_limits_or_none(self) -> None:
        limiter = _WeightedRateLimiter(_tokens_config())
        costs, _ = limiter.reserve(("x" * 90,), {})
        assert costs == [1.0, 90.0]

        costs, blocker = limiter.reserve(("x" * 20,), {})
        assert costs is None
        assert blocker == "tokens"
        # The rejected call consumed nothing from the call limit either
        levels = limiter.levels()
        assert levels["calls"] == pytest.approx(9.0, abs=0.01)
        assert levels["tokens"] == pytest.approx(10.0, abs=0.1)

    def test_second_window_blocks_first(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=5, period=LONG, limits=[RateLimit(2, LONG, name="burst")])
        )
        assert limiter.acquire() is True
        assert limiter.acquire() is True
        costs, blocker = limiter.reserve((), {})
        assert costs is None
        assert blocker == "burst"

    def test_cost_above_capacity_is_rejected_without_waiting(self) -> None:
        limiter = _WeightedRateLimiter(_tokens_config(max_wait=5.0))
        start = time.monotonic()
        costs, blocker = limiter.reserve(("x" * 500,), {})
        assert costs is None
        assert blocker == "tokens"
        assert time.monotonic() - start < 1.0

    def test_negative_cost_counts_as_zero(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=10, period=LONG, cost=lambda: -5.0)
        )
        costs, _ = limiter.reserve((), {})
        assert costs == [0.0]
        assert limiter.levels()["calls"] == pytest.approx(10.0, abs=0.01)

    def test_waits_for_capacity_within_max_wait(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=1, period=0.1, max_wait=2.0, charge_retries=True)
        )
        assert limiter.acquire() is True
        start = time.monotonic()
        assert limiter.acquire() is True
        # One token refills in 0.1s (use 0.05 for Windows timer precision)
        assert time.monotonic() - start >= 0.05

    def test_rejects_at_once_when_wait_cannot_succeed(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=1, period=LONG, max_wait=3.0, charge_retries=True)
        )
        assert limiter.acquire() is True
        start = time.monotonic()
        assert limiter.acquire() is False
        # Capacity returns in an hour; waiting 3s is pointless, so there is no wait
        assert time.monotonic() - start < 1.5

    def test_reset_refills_and_unpauses(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(
                max_calls=1,
                period=LONG,
                feedback=lambda outcome: RateLimitFeedback(retry_after=30.0),
            )
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        limiter.bind(lambda: "ok", costs)()
        assert limiter.acquire() is False
        limiter.reset()
        assert limiter.acquire() is True

    def test_thread_safe_exact_capacity(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=100, period=LONG, charge_retries=True)
        )
        granted: list[bool] = []
        lock = threading.Lock()

        def worker() -> None:
            for _ in range(50):
                ok = limiter.acquire()
                with lock:
                    granted.append(ok)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert len(granted) == 400
        assert sum(granted) == 100


class TestWeightedRateLimiterAsync:
    async def test_all_limits_or_none(self) -> None:
        limiter = _AsyncWeightedRateLimiter(_tokens_config())
        costs, _ = await limiter.reserve(("x" * 90,), {})
        assert costs == [1.0, 90.0]
        costs, blocker = await limiter.reserve(("x" * 20,), {})
        assert costs is None
        assert blocker == "tokens"
        assert limiter.levels()["calls"] == pytest.approx(9.0, abs=0.01)

    async def test_acquire_without_arguments(self) -> None:
        limiter = _AsyncWeightedRateLimiter(
            RateLimiterConfig(max_calls=2, period=LONG, charge_retries=True)
        )
        assert await limiter.acquire() is True
        assert await limiter.acquire() is True
        assert await limiter.acquire() is False

    async def test_waits_for_capacity_within_max_wait(self) -> None:
        limiter = _AsyncWeightedRateLimiter(
            RateLimiterConfig(max_calls=1, period=0.1, max_wait=2.0, charge_retries=True)
        )
        assert await limiter.acquire() is True
        start = time.monotonic()
        assert await limiter.acquire() is True
        assert time.monotonic() - start >= 0.05

    async def test_rejects_at_once_when_wait_cannot_succeed(self) -> None:
        limiter = _AsyncWeightedRateLimiter(
            RateLimiterConfig(max_calls=1, period=LONG, max_wait=3.0, charge_retries=True)
        )
        assert await limiter.acquire() is True
        start = time.monotonic()
        assert await limiter.acquire() is False
        assert time.monotonic() - start < 1.5

    async def test_reconcile_and_feedback(self) -> None:
        config = RateLimiterConfig(
            max_calls=10,
            period=LONG,
            limits=[
                RateLimit(
                    100, LONG, name="tokens", cost=lambda: 50, actual_cost=lambda result: result
                )
            ],
            feedback=lambda outcome: RateLimitFeedback(retry_after=30.0),
        )
        limiter = _AsyncWeightedRateLimiter(config)
        assert limiter.observes is True
        costs, _ = await limiter.reserve((), {})
        assert costs is not None

        async def call() -> int:
            return 20

        assert await limiter.bind(call, costs)() == 20
        assert limiter.levels()["tokens"] == pytest.approx(80.0, abs=0.1)
        costs, blocker = await limiter.reserve((), {})
        assert costs is None
        assert blocker == "server feedback"
        limiter.reset()
        assert await limiter.acquire() is True

    async def test_feedback_sees_the_raised_exception(self) -> None:
        seen: list[Any] = []

        def feedback(outcome: Any) -> Optional[RateLimitFeedback]:
            seen.append(outcome)
            return None

        limiter = _AsyncWeightedRateLimiter(
            RateLimiterConfig(max_calls=10, period=LONG, feedback=feedback)
        )
        costs, _ = await limiter.reserve((), {})
        assert costs is not None

        async def boom() -> None:
            raise ValueError("429")

        with pytest.raises(ValueError):
            await limiter.bind(boom, costs)()
        assert isinstance(seen[0], ValueError)

    async def test_charge_retries_debits_every_attempt(self) -> None:
        limiter = _AsyncWeightedRateLimiter(
            RateLimiterConfig(max_calls=10, period=LONG, charge_retries=True)
        )
        costs, _ = await limiter.reserve((), {})
        assert costs is not None

        async def call() -> str:
            return "ok"

        bound = limiter.bind(call, costs)
        await bound()
        await bound()
        assert limiter.levels()["calls"] == pytest.approx(8.0, abs=0.01)

    async def test_retries_are_free_without_charge_retries(self) -> None:
        limiter = _AsyncWeightedRateLimiter(
            RateLimiterConfig(max_calls=10, period=LONG, feedback=lambda outcome: None)
        )
        costs, _ = await limiter.reserve((), {})
        assert costs is not None

        async def call() -> str:
            return "ok"

        bound = limiter.bind(call, costs)
        await bound()
        await bound()
        assert limiter.levels()["calls"] == pytest.approx(9.0, abs=0.01)
