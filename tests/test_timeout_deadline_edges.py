"""Edge cases of the overall deadline: events, retry budget, bulkhead waits."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from pyresilience import (
    BulkheadConfig,
    EventType,
    ResilienceEvent,
    ResilienceTimeoutError,
    RetryBudget,
    RetryBudgetConfig,
    RetryConfig,
    TimeoutConfig,
    resilient,
)


class TestDeadlineEvents:
    def test_one_timeout_event_when_the_attempt_hits_the_deadline(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.5, jitter=False),
            timeout=TimeoutConfig(seconds=5.0, total_seconds=0.3),
            listeners=[events.append],
        )
        def slow() -> str:
            time.sleep(1.0)
            return "late"

        with pytest.raises(ResilienceTimeoutError, match="total timeout budget"):
            slow()

        timeouts = [e for e in events if e.event_type == EventType.TIMEOUT]
        # The attempt reports its own timeout; the deadline stop adds no second one
        assert len(timeouts) == 1
        # ...and it names the time the attempt really had, not the 5s limit
        assert timeouts[0].detail != "exceeded 5.0s"
        assert events[-1].event_type == EventType.FAILURE

    async def test_one_timeout_event_when_the_attempt_hits_the_deadline_async(self) -> None:
        events: list[ResilienceEvent] = []

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.5, jitter=False),
            timeout=TimeoutConfig(seconds=5.0, total_seconds=0.3),
            listeners=[events.append],
        )
        async def slow() -> str:
            await asyncio.sleep(1.0)
            return "late"

        with pytest.raises(ResilienceTimeoutError, match="total timeout budget") as info:
            await slow()

        timeouts = [e for e in events if e.event_type == EventType.TIMEOUT]
        assert len(timeouts) == 1
        assert timeouts[0].detail != "exceeded 5.0s"
        # The attempt's own error reports the clamped limit as well
        assert "5.0s" not in str(info.value.__cause__)


class TestDeadlineAndRetryBudget:
    def test_refund_returns_a_token(self) -> None:
        budget = RetryBudget(RetryBudgetConfig(max_retries=3, refill_rate=0.0001))
        assert budget.acquire() is True
        assert budget.available == pytest.approx(2.0, abs=0.01)
        budget.refund()
        assert budget.available == pytest.approx(3.0, abs=0.01)
        budget.refund()  # never above capacity
        assert budget.available == pytest.approx(3.0, abs=0.01)

    def test_no_budget_token_is_spent_on_a_retry_the_deadline_prevents(self) -> None:
        @resilient(
            retry=RetryConfig(max_attempts=5, delay=1.0, jitter=False),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            retry_budget=RetryBudgetConfig(max_retries=10, refill_rate=0.0001),
        )
        def always_fails() -> str:
            raise ValueError("boom")

        with pytest.raises(ResilienceTimeoutError):
            always_fails()
        budget = always_fails._executor._retry_budget  # type: ignore[attr-defined]
        assert budget.available == pytest.approx(10.0, abs=0.01)

    def test_no_budget_token_is_spent_on_the_result_path(self) -> None:
        @resilient(
            retry=RetryConfig(
                max_attempts=5, delay=1.0, jitter=False, retry_on_result=lambda r: True
            ),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            retry_budget=RetryBudgetConfig(max_retries=10, refill_rate=0.0001),
        )
        def pending() -> str:
            return "pending"

        assert pending() == "pending"
        budget = pending._executor._retry_budget  # type: ignore[attr-defined]
        assert budget.available == pytest.approx(10.0, abs=0.01)

    async def test_no_budget_token_is_spent_async(self) -> None:
        @resilient(
            retry=RetryConfig(max_attempts=5, delay=1.0, jitter=False),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            retry_budget=RetryBudgetConfig(max_retries=10, refill_rate=0.0001),
        )
        async def always_fails() -> str:
            raise ValueError("boom")

        with pytest.raises(ResilienceTimeoutError):
            await always_fails()
        budget = always_fails._executor._retry_budget  # type: ignore[attr-defined]
        assert budget.available == pytest.approx(10.0, abs=0.01)

    async def test_no_budget_token_is_spent_on_the_result_path_async(self) -> None:
        @resilient(
            retry=RetryConfig(
                max_attempts=5, delay=1.0, jitter=False, retry_on_result=lambda r: True
            ),
            timeout=TimeoutConfig(seconds=1.0, total_seconds=0.2),
            retry_budget=RetryBudgetConfig(max_retries=10, refill_rate=0.0001),
        )
        async def pending() -> str:
            return "pending"

        assert await pending() == "pending"
        budget = pending._executor._retry_budget  # type: ignore[attr-defined]
        assert budget.available == pytest.approx(10.0, abs=0.01)


class TestDeadlineAndBulkheadWait:
    """A retrying call gives its bulkhead slot back while it sleeps.

    If another call takes the slot and keeps it until that call's own deadline, the
    first call gets the slot back only after its deadline has passed. It must then
    stop instead of running another attempt.
    """

    def test_bulkhead_wait_past_the_deadline_stops_the_call(self) -> None:
        release_holder = threading.Event()
        first_attempt_done = threading.Event()
        attempts = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.1, jitter=False),
            timeout=TimeoutConfig(seconds=5.0, total_seconds=0.4),
            bulkhead=BulkheadConfig(max_concurrent=1, max_wait=5.0),
        )
        def work(hold: bool) -> str:
            nonlocal attempts
            if hold:
                release_holder.wait(timeout=5.0)
                return "held"
            attempts += 1
            first_attempt_done.set()
            raise ValueError("boom")

        outcomes: dict[str, BaseException] = {}

        def call(name: str, hold: bool) -> None:
            try:
                work(hold)
            except BaseException as exc:
                outcomes[name] = exc

        caller = threading.Thread(target=call, args=("failing", False))
        caller.start()
        assert first_attempt_done.wait(timeout=5.0)
        # While the failing call sleeps before its retry, this call takes the only slot.
        # It started later, so its own deadline (and the slot) comes after the other one.
        holder = threading.Thread(target=call, args=("holder", True))
        holder.start()
        caller.join(timeout=10.0)
        release_holder.set()
        holder.join(timeout=10.0)

        assert isinstance(outcomes["holder"], ResilienceTimeoutError)
        assert isinstance(outcomes["failing"], ResilienceTimeoutError)
        assert "total timeout budget" in str(outcomes["failing"])
        # No second attempt: the deadline had passed when the slot came back
        assert attempts == 1

    async def test_bulkhead_wait_past_the_deadline_stops_the_call_async(self) -> None:
        first_attempt_done = asyncio.Event()
        attempts = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.1, jitter=False),
            timeout=TimeoutConfig(seconds=5.0, total_seconds=0.4),
            bulkhead=BulkheadConfig(max_concurrent=1, max_wait=5.0),
        )
        async def work(hold: bool) -> str:
            nonlocal attempts
            if hold:
                await asyncio.sleep(5.0)
                return "held"
            attempts += 1
            first_attempt_done.set()
            raise ValueError("boom")

        failing = asyncio.ensure_future(work(False))
        await first_attempt_done.wait()
        holder = asyncio.ensure_future(work(True))

        with pytest.raises(ResilienceTimeoutError):
            await holder
        with pytest.raises(ResilienceTimeoutError, match="total timeout budget"):
            await failing
        assert attempts == 1
