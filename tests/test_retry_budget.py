"""Tests for retry budget (token bucket)."""

from __future__ import annotations

import time

import pytest

from pyresilience._retry_budget import RetryBudget
from pyresilience._types import RetryBudgetConfig


class TestRetryBudget:
    def test_starts_full(self) -> None:
        """Token bucket starts at full capacity."""
        budget = RetryBudget(RetryBudgetConfig(max_retries=5, refill_rate=1.0))
        assert budget.available >= 4.9  # Allow small float rounding

    def test_acquire_until_depleted(self) -> None:
        """acquire() returns True until tokens are exhausted."""
        budget = RetryBudget(RetryBudgetConfig(max_retries=3, refill_rate=0.0001))
        assert budget.acquire() is True
        assert budget.acquire() is True
        assert budget.acquire() is True
        assert budget.acquire() is False

    def test_acquire_returns_false_when_empty(self) -> None:
        """acquire() returns False when no tokens available."""
        budget = RetryBudget(RetryBudgetConfig(max_retries=1, refill_rate=0.0001))
        budget.acquire()  # consume the only token
        assert budget.acquire() is False

    def test_tokens_refill_over_time(self) -> None:
        """Tokens refill based on refill_rate after time passes."""
        budget = RetryBudget(RetryBudgetConfig(max_retries=2, refill_rate=100.0))
        # Drain all tokens
        budget.acquire()
        budget.acquire()
        assert budget.acquire() is False

        # Wait for refill (100 tokens/sec, so 0.05s gives ~5 tokens, capped at 2)
        time.sleep(0.05)
        assert budget.acquire() is True

    def test_reset_refills_to_max(self) -> None:
        """reset() restores tokens to full capacity."""
        budget = RetryBudget(RetryBudgetConfig(max_retries=3, refill_rate=0.0001))
        budget.acquire()
        budget.acquire()
        budget.acquire()
        assert budget.acquire() is False

        budget.reset()
        assert budget.available >= 2.9
        assert budget.acquire() is True

    def test_tokens_capped_at_capacity(self) -> None:
        """Tokens cannot exceed max_retries even after long time."""
        budget = RetryBudget(RetryBudgetConfig(max_retries=5, refill_rate=1000.0))
        time.sleep(0.05)
        assert budget.available <= 5.0


class TestRetryBudgetConfig:
    def test_max_retries_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_retries must be >= 1"):
            RetryBudgetConfig(max_retries=0)

    def test_refill_rate_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="refill_rate must be > 0"):
            RetryBudgetConfig(refill_rate=0)


class TestRetryBudgetIntegration:
    def test_retry_budget_limits_retries(self) -> None:
        """RetryBudgetConfig in ResilienceConfig limits retries across calls."""
        from pyresilience import resilient
        from pyresilience._types import RetryConfig

        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=10, delay=0.01, jitter=False),
            retry_budget=RetryBudgetConfig(max_retries=2, refill_rate=0.0001),
        )
        def failing_func() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("always fails")

        with pytest.raises(ValueError):
            failing_func()

        # With budget of 2 retries: 1 initial + 2 retries = 3 calls max
        assert call_count == 3

    def test_shared_budget_across_functions(self) -> None:
        """Multiple functions sharing a RetryBudget exhaust the shared budget."""
        from pyresilience import ResilienceConfig, ResilienceRegistry
        from pyresilience._types import RetryConfig

        registry = ResilienceRegistry()
        registry.register(
            "api",
            ResilienceConfig(
                retry=RetryConfig(max_attempts=10, delay=0.01, jitter=False),
                retry_budget=RetryBudgetConfig(max_retries=3, refill_rate=0.0001),
            ),
        )

        count_a = 0
        count_b = 0

        @registry.decorator("api")
        def func_a() -> str:
            nonlocal count_a
            count_a += 1
            raise ValueError("fail a")

        @registry.decorator("api")
        def func_b() -> str:
            nonlocal count_b
            count_b += 1
            raise ValueError("fail b")

        # func_a: 1 initial + retries (up to 3 budget tokens)
        with pytest.raises(ValueError):
            func_a()

        # func_b: budget should be partially/fully exhausted by func_a
        with pytest.raises(ValueError):
            func_b()

        # Total retries across both functions should be limited by the shared budget
        total_retries = (count_a - 1) + (count_b - 1)  # subtract initial calls
        assert total_retries <= 3


class TestRetryBudgetAsync:
    @pytest.mark.asyncio
    async def test_async_retry_budget_limits_retries(self) -> None:
        """RetryBudgetConfig limits retries for async functions too."""
        from pyresilience import resilient
        from pyresilience._types import RetryConfig

        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=10, delay=0.01, jitter=False),
            retry_budget=RetryBudgetConfig(max_retries=2, refill_rate=0.0001),
        )
        async def failing_func() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("always fails")

        with pytest.raises(ValueError):
            await failing_func()

        # 1 initial + 2 retries = 3 calls max
        assert call_count == 3


class TestRetryBudgetOnResult:
    @pytest.mark.parametrize("with_listeners", [False, True])
    def test_result_retries_stop_at_budget(self, with_listeners: bool) -> None:
        from pyresilience import EventType, ResilienceEvent, RetryConfig, resilient

        call_count = 0
        delay_count = 0
        events: list[ResilienceEvent] = []

        def delay_func(attempt: int, result: object) -> float:
            nonlocal delay_count
            delay_count += 1
            return 0.0

        @resilient(
            retry=RetryConfig(
                max_attempts=10,
                retry_on_result=lambda result: True,
                delay_func=delay_func,
            ),
            retry_budget=RetryBudgetConfig(max_retries=2, refill_rate=0.0001),
            listeners=[events.append] if with_listeners else [],
        )
        def pending() -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        assert pending() == 3
        assert call_count == 3
        assert delay_count == 2
        if with_listeners:
            assert [event.event_type for event in events] == [
                EventType.RETRY,
                EventType.RETRY,
                EventType.RETRY_EXHAUSTED,
            ]
            assert events[-1].detail == "retry budget exhausted"
            assert events[-1].attempt == 3

        events.clear()
        assert pending() == 4
        assert call_count == 4
        assert delay_count == 2
        if with_listeners:
            assert [event.event_type for event in events] == [EventType.RETRY_EXHAUSTED]
            assert events[0].detail == "retry budget exhausted"
            assert events[0].attempt == 1
        else:
            assert events == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("with_listeners", [False, True])
    async def test_async_result_retries_stop_at_budget(self, with_listeners: bool) -> None:
        from pyresilience import EventType, ResilienceEvent, RetryConfig, resilient

        call_count = 0
        delay_count = 0
        events: list[ResilienceEvent] = []

        def delay_func(attempt: int, result: object) -> float:
            nonlocal delay_count
            delay_count += 1
            return 0.0

        @resilient(
            retry=RetryConfig(
                max_attempts=10,
                retry_on_result=lambda result: True,
                delay_func=delay_func,
            ),
            retry_budget=RetryBudgetConfig(max_retries=2, refill_rate=0.0001),
            listeners=[events.append] if with_listeners else [],
        )
        async def pending() -> int:
            nonlocal call_count
            call_count += 1
            return call_count

        assert await pending() == 3
        assert call_count == 3
        assert delay_count == 2
        if with_listeners:
            assert [event.event_type for event in events] == [
                EventType.RETRY,
                EventType.RETRY,
                EventType.RETRY_EXHAUSTED,
            ]
            assert events[-1].detail == "retry budget exhausted"
            assert events[-1].attempt == 3

        events.clear()
        assert await pending() == 4
        assert call_count == 4
        assert delay_count == 2
        if with_listeners:
            assert [event.event_type for event in events] == [EventType.RETRY_EXHAUSTED]
            assert events[0].detail == "retry budget exhausted"
            assert events[0].attempt == 1
        else:
            assert events == []

    @pytest.mark.parametrize("exception_first", [False, True])
    def test_result_and_exception_retries_share_budget(self, exception_first: bool) -> None:
        from pyresilience import RetryConfig, resilient

        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=10,
                delay=0,
                retry_on_result=lambda result: True,
            ),
            retry_budget=RetryBudgetConfig(max_retries=2, refill_rate=0.0001),
        )
        def alternating() -> int:
            nonlocal call_count
            call_count += 1
            if (call_count % 2 == 1) == exception_first:
                raise ValueError(f"attempt {call_count}")
            return call_count

        if exception_first:
            with pytest.raises(ValueError, match="attempt 3"):
                alternating()
        else:
            assert alternating() == 3
        assert call_count == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exception_first", [False, True])
    async def test_async_result_and_exception_retries_share_budget(
        self, exception_first: bool
    ) -> None:
        from pyresilience import RetryConfig, resilient

        call_count = 0

        @resilient(
            retry=RetryConfig(
                max_attempts=10,
                delay=0,
                retry_on_result=lambda result: True,
            ),
            retry_budget=RetryBudgetConfig(max_retries=2, refill_rate=0.0001),
        )
        async def alternating() -> int:
            nonlocal call_count
            call_count += 1
            if (call_count % 2 == 1) == exception_first:
                raise ValueError(f"attempt {call_count}")
            return call_count

        if exception_first:
            with pytest.raises(ValueError, match="attempt 3"):
                await alternating()
        else:
            assert await alternating() == 3
        assert call_count == 3

    @pytest.mark.parametrize("retry_result", [False, True])
    def test_returned_result_preserves_unused_budget(self, retry_result: bool) -> None:
        from pyresilience import ResilienceConfig, ResilienceRegistry, RetryConfig

        registry = ResilienceRegistry()
        registry.register(
            "api",
            ResilienceConfig(
                retry=RetryConfig(
                    max_attempts=2,
                    delay=0,
                    retry_on_result=lambda result: result == "pending",
                ),
                retry_budget=RetryBudgetConfig(max_retries=2, refill_rate=0.0001),
            ),
        )
        result_calls = 0
        exception_calls = 0

        @registry.decorator("api")
        def returning() -> str:
            nonlocal result_calls
            result_calls += 1
            return "pending" if retry_result else "ready"

        @registry.decorator("api")
        def failing() -> str:
            nonlocal exception_calls
            exception_calls += 1
            raise ValueError("unavailable")

        assert returning() == ("pending" if retry_result else "ready")
        assert result_calls == (2 if retry_result else 1)
        remaining_retries = 1 if retry_result else 2
        for call in range(remaining_retries):
            with pytest.raises(ValueError, match="unavailable"):
                failing()
            assert exception_calls == 2 * (call + 1)
        with pytest.raises(ValueError, match="unavailable"):
            failing()
        assert exception_calls == 2 * remaining_retries + 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("retry_result", [False, True])
    async def test_async_returned_result_preserves_unused_budget(self, retry_result: bool) -> None:
        from pyresilience import ResilienceConfig, ResilienceRegistry, RetryConfig

        registry = ResilienceRegistry()
        registry.register(
            "api",
            ResilienceConfig(
                retry=RetryConfig(
                    max_attempts=2,
                    delay=0,
                    retry_on_result=lambda result: result == "pending",
                ),
                retry_budget=RetryBudgetConfig(max_retries=2, refill_rate=0.0001),
            ),
        )
        result_calls = 0
        exception_calls = 0

        @registry.decorator("api")
        async def returning() -> str:
            nonlocal result_calls
            result_calls += 1
            return "pending" if retry_result else "ready"

        @registry.decorator("api")
        async def failing() -> str:
            nonlocal exception_calls
            exception_calls += 1
            raise ValueError("unavailable")

        assert await returning() == ("pending" if retry_result else "ready")
        assert result_calls == (2 if retry_result else 1)
        remaining_retries = 1 if retry_result else 2
        for call in range(remaining_retries):
            with pytest.raises(ValueError, match="unavailable"):
                await failing()
            assert exception_calls == 2 * (call + 1)
        with pytest.raises(ValueError, match="unavailable"):
            await failing()
        assert exception_calls == 2 * remaining_retries + 1
