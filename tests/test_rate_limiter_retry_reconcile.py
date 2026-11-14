"""Tests for how a reservation is settled when a call is retried."""

from __future__ import annotations

from typing import Any

import pytest

from pyresilience import RateLimit, RateLimiterConfig, RetryConfig, resilient

LONG = 3600.0


def _config(charge_retries: bool = False) -> RateLimiterConfig:
    """10,000 tokens; every call reserves 1,000 and reports its real usage."""
    return RateLimiterConfig(
        max_calls=100,
        period=LONG,
        charge_retries=charge_retries,
        limits=[
            RateLimit(
                10_000,
                LONG,
                name="tokens",
                cost=lambda: 1000,
                actual_cost=lambda response: response["usage"],
            )
        ],
    )


def _tokens_used(func: Any) -> float:
    levels = func._executor._weighted_limiter.levels()
    return 10_000 - levels["tokens"]


class TestRetryReconcileSync:
    def test_successful_retry_settles_the_one_reservation(self) -> None:
        attempts = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            rate_limiter=_config(),
        )
        def complete() -> dict[str, int]:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("first attempt fails")
            return {"usage": 800}

        complete()
        # One reservation of 1,000, settled to the 800 really used: not 1,800
        assert _tokens_used(complete) == pytest.approx(800.0, abs=1.0)

    def test_all_attempts_failing_keeps_the_estimate(self) -> None:
        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            rate_limiter=_config(),
        )
        def complete() -> dict[str, int]:
            raise ConnectionError("down")

        with pytest.raises(ConnectionError):
            complete()
        assert _tokens_used(complete) == pytest.approx(1000.0, abs=1.0)

    def test_every_attempt_that_reports_usage_is_counted(self) -> None:
        answers = [{"usage": 300, "retry": True}, {"usage": 500, "retry": False}]

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.01,
                jitter=False,
                retry_on_result=lambda response: response["retry"],
            ),
            rate_limiter=_config(),
        )
        def complete() -> dict[str, Any]:
            return answers.pop(0)

        complete()
        # The first response settles the reservation (300); the retry adds its own 500
        assert _tokens_used(complete) == pytest.approx(800.0, abs=1.0)

    def test_charge_retries_reserves_again_for_every_retry(self) -> None:
        attempts = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            rate_limiter=_config(charge_retries=True),
        )
        def complete() -> dict[str, int]:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("first attempt fails")
            return {"usage": 800}

        complete()
        # The failed attempt keeps its 1,000; the retry reserved 1,000 and used 800
        assert _tokens_used(complete) == pytest.approx(1800.0, abs=1.0)


class TestRetryReconcileAsync:
    async def test_successful_retry_settles_the_one_reservation(self) -> None:
        attempts = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            rate_limiter=_config(),
        )
        async def complete() -> dict[str, int]:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("first attempt fails")
            return {"usage": 800}

        await complete()
        assert _tokens_used(complete) == pytest.approx(800.0, abs=1.0)

    async def test_all_attempts_failing_keeps_the_estimate(self) -> None:
        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            rate_limiter=_config(),
        )
        async def complete() -> dict[str, int]:
            raise ConnectionError("down")

        with pytest.raises(ConnectionError):
            await complete()
        assert _tokens_used(complete) == pytest.approx(1000.0, abs=1.0)

    async def test_every_attempt_that_reports_usage_is_counted(self) -> None:
        answers = [{"usage": 300, "retry": True}, {"usage": 500, "retry": False}]

        @resilient(
            retry=RetryConfig(
                max_attempts=3,
                delay=0.01,
                jitter=False,
                retry_on_result=lambda response: response["retry"],
            ),
            rate_limiter=_config(),
        )
        async def complete() -> dict[str, Any]:
            return answers.pop(0)

        await complete()
        assert _tokens_used(complete) == pytest.approx(800.0, abs=1.0)

    async def test_charge_retries_reserves_again_for_every_retry(self) -> None:
        attempts = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01, jitter=False),
            rate_limiter=_config(charge_retries=True),
        )
        async def complete() -> dict[str, int]:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ConnectionError("first attempt fails")
            return {"usage": 800}

        await complete()
        assert _tokens_used(complete) == pytest.approx(1800.0, abs=1.0)
