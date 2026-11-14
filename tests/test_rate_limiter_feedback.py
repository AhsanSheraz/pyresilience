"""Tests for rate-limit reconciliation, server feedback and charged retries."""

from __future__ import annotations

import time
from typing import Any, Optional

import pytest

from pyresilience import (
    RateLimit,
    RateLimiterConfig,
    RateLimitFeedback,
)
from pyresilience._weighted_limiter import (
    _WeightedRateLimiter,
)

# A long period keeps refill negligible, so levels are deterministic.
LONG = 3600.0


class TestReconcileAndFeedbackSync:
    def test_actual_cost_gives_back_the_unused_estimate(self) -> None:
        config = RateLimiterConfig(
            max_calls=10,
            period=LONG,
            limits=[
                RateLimit(
                    100, LONG, name="tokens", cost=lambda: 50, actual_cost=lambda result: result
                )
            ],
        )
        limiter = _WeightedRateLimiter(config)
        assert limiter.observes is True
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        assert limiter.bind(lambda: 20, costs)() == 20
        assert limiter.levels()["tokens"] == pytest.approx(80.0, abs=0.1)

    def test_actual_cost_above_estimate_creates_debt(self) -> None:
        config = RateLimiterConfig(
            max_calls=10,
            period=LONG,
            limits=[
                RateLimit(
                    100, LONG, name="tokens", cost=lambda: 10, actual_cost=lambda result: result
                )
            ],
        )
        limiter = _WeightedRateLimiter(config)
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        limiter.bind(lambda: 150, costs)()
        assert limiter.levels()["tokens"] < 0
        costs, blocker = limiter.reserve((), {})
        assert costs is None
        assert blocker == "tokens"

    def test_actual_cost_on_primary_limit(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(
                max_calls=10, period=LONG, cost=lambda: 5, actual_cost=lambda result: 2
            )
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        limiter.bind(lambda: "ok", costs)()
        assert limiter.levels()["calls"] == pytest.approx(8.0, abs=0.01)

    def test_actual_cost_none_keeps_the_estimate(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(
                max_calls=10, period=LONG, cost=lambda: 5, actual_cost=lambda result: None
            )
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        limiter.bind(lambda: "ok", costs)()
        assert limiter.levels()["calls"] == pytest.approx(5.0, abs=0.01)

    def test_actual_cost_error_never_breaks_the_call(self) -> None:
        def broken(result: Any) -> float:
            raise RuntimeError("bad usage parser")

        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=10, period=LONG, cost=lambda: 5, actual_cost=broken)
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        assert limiter.bind(lambda: "ok", costs)() == "ok"
        assert limiter.levels()["calls"] == pytest.approx(5.0, abs=0.01)

    def test_failed_call_keeps_the_estimate_charged(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(
                max_calls=10, period=LONG, cost=lambda: 5, actual_cost=lambda result: 0
            )
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None

        def boom() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            limiter.bind(boom, costs)()
        assert limiter.levels()["calls"] == pytest.approx(5.0, abs=0.01)

    def test_feedback_retry_after_pauses_then_resumes(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(
                max_calls=10,
                period=LONG,
                feedback=lambda outcome: RateLimitFeedback(retry_after=0.3),
            )
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        limiter.bind(lambda: "ok", costs)()

        costs, blocker = limiter.reserve((), {})
        assert costs is None
        assert blocker == "server feedback"
        assert limiter._core.paused_for() > 0

        time.sleep(0.4)
        assert limiter._core.paused_for() == 0.0
        assert limiter.acquire() is True

    def test_feedback_pause_is_waited_out_within_max_wait(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(
                max_calls=10,
                period=LONG,
                max_wait=2.0,
                feedback=lambda outcome: RateLimitFeedback(retry_after=0.2),
            )
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        limiter.bind(lambda: "ok", costs)()
        start = time.monotonic()
        assert limiter.acquire() is True
        assert time.monotonic() - start >= 0.1

    def test_feedback_remaining_lowers_but_never_raises_a_level(self) -> None:
        answers = [
            RateLimitFeedback(remaining={"calls": 2}),
            RateLimitFeedback(remaining={"calls": 9, "unknown": 1}),
        ]
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=10, period=LONG, feedback=lambda outcome: answers.pop(0))
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        limiter.bind(lambda: "ok", costs)()
        assert limiter.levels()["calls"] == pytest.approx(2.0, abs=0.01)

        costs, _ = limiter.reserve((), {})
        assert costs is not None
        limiter.bind(lambda: "ok", costs)()
        assert limiter.levels()["calls"] == pytest.approx(1.0, abs=0.01)

    def test_feedback_sees_the_raised_exception(self) -> None:
        seen: list[Any] = []

        def feedback(outcome: Any) -> Optional[RateLimitFeedback]:
            seen.append(outcome)
            return RateLimitFeedback(retry_after=30.0)

        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=10, period=LONG, feedback=feedback)
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None

        def boom() -> None:
            raise ValueError("429")

        with pytest.raises(ValueError):
            limiter.bind(boom, costs)()
        assert isinstance(seen[0], ValueError)
        assert limiter.acquire() is False

    def test_feedback_error_never_breaks_the_call(self) -> None:
        def broken(outcome: Any) -> RateLimitFeedback:
            raise RuntimeError("bad header parser")

        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=10, period=LONG, feedback=broken)
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        assert limiter.bind(lambda: "ok", costs)() == "ok"
        assert limiter.acquire() is True

    def test_feedback_none_changes_nothing(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=10, period=LONG, feedback=lambda outcome: None)
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        limiter.bind(lambda: "ok", costs)()
        assert limiter.levels()["calls"] == pytest.approx(9.0, abs=0.01)

    def test_charge_retries_debits_every_attempt(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=10, period=LONG, charge_retries=True)
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        bound = limiter.bind(lambda: "ok", costs)
        bound()
        bound()
        bound()
        assert limiter.levels()["calls"] == pytest.approx(7.0, abs=0.01)

    def test_retries_are_free_without_charge_retries(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(max_calls=10, period=LONG, feedback=lambda outcome: None)
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        bound = limiter.bind(lambda: "ok", costs)
        bound()
        bound()
        assert limiter.levels()["calls"] == pytest.approx(9.0, abs=0.01)

    def test_uncharged_retry_is_debited_its_actual_cost(self) -> None:
        limiter = _WeightedRateLimiter(
            RateLimiterConfig(
                max_calls=100, period=LONG, cost=lambda: 10, actual_cost=lambda result: 10
            )
        )
        costs, _ = limiter.reserve((), {})
        assert costs is not None
        bound = limiter.bind(lambda: "ok", costs)
        bound()
        assert limiter.levels()["calls"] == pytest.approx(90.0, abs=0.1)
        bound()  # a retry: nothing was reserved for it, so its real usage is debited
        assert limiter.levels()["calls"] == pytest.approx(80.0, abs=0.1)
