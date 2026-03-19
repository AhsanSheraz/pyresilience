"""Tests for structured logging and metrics."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

from pyresilience import (
    EventType,
    JsonEventLogger,
    MetricsCollector,
    ResilienceEvent,
    RetryConfig,
    resilient,
)


class TestJsonEventLogger:
    def test_logs_events(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = JsonEventLogger(level=logging.INFO)

        with caplog.at_level(logging.INFO, logger="pyresilience"):
            event = ResilienceEvent(
                event_type=EventType.SUCCESS,
                function_name="test_func",
                attempt=1,
            )
            logger(event)

        assert len(caplog.records) == 1
        data = json.loads(caplog.records[0].message)
        assert data["event"] == "success"
        assert data["function"] == "test_func"
        assert data["attempt"] == 1
        assert "timestamp" in data

    def test_logs_error_details(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = JsonEventLogger(level=logging.WARNING)

        with caplog.at_level(logging.WARNING, logger="pyresilience"):
            event = ResilienceEvent(
                event_type=EventType.RETRY,
                function_name="failing_func",
                attempt=2,
                error=ValueError("connection refused"),
                detail="retrying in 1.5s",
            )
            logger(event)

        data = json.loads(caplog.records[0].message)
        assert data["error_type"] == "ValueError"
        assert data["error_message"] == "connection refused"
        assert data["detail"] == "retrying in 1.5s"

    def test_no_timestamp(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = JsonEventLogger(include_timestamp=False)

        with caplog.at_level(logging.INFO, logger="pyresilience"):
            event = ResilienceEvent(
                event_type=EventType.SUCCESS,
                function_name="test_func",
                attempt=1,
            )
            logger(event)

        data = json.loads(caplog.records[0].message)
        assert "timestamp" not in data

    def test_integrated_with_decorator(self, caplog: pytest.LogCaptureFixture) -> None:
        logger = JsonEventLogger()
        call_count = 0

        @resilient(retry=RetryConfig(max_attempts=2, delay=0.01), listeners=[logger])
        def fails_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("fail")
            return "ok"

        with caplog.at_level(logging.INFO, logger="pyresilience"):
            fails_once()

        assert len(caplog.records) >= 2
        events = [json.loads(r.message)["event"] for r in caplog.records]
        assert "retry" in events
        assert "success" in events


class TestMetricsCollector:
    def test_counts_events(self) -> None:
        metrics = MetricsCollector()
        call_count = 0

        @resilient(retry=RetryConfig(max_attempts=2, delay=0.01), listeners=[metrics])
        def fails_once() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("fail")
            return "ok"

        fails_once()

        counts = metrics.get_counts("fails_once")
        assert counts["fails_once"]["retry"] == 1
        assert counts["fails_once"]["success"] == 1

    def test_summary(self) -> None:
        metrics = MetricsCollector()

        @resilient(retry=RetryConfig(max_attempts=1, delay=0.01), listeners=[metrics])
        def ok_func() -> str:
            return "ok"

        ok_func()
        ok_func()

        summary = metrics.summary()
        assert "ok_func" in summary
        assert summary["ok_func"]["total_calls"] == 2
        assert summary["ok_func"]["success_rate"] == 1.0

    def test_reset(self) -> None:
        metrics = MetricsCollector()

        @resilient(retry=RetryConfig(max_attempts=1, delay=0.01), listeners=[metrics])
        def ok_func() -> str:
            return "ok"

        ok_func()
        assert len(metrics.get_counts()) > 0
        metrics.reset()
        assert len(metrics.get_counts()) == 0

    def test_get_latencies(self) -> None:
        metrics = MetricsCollector()

        @resilient(retry=RetryConfig(max_attempts=1, delay=0.01), listeners=[metrics])
        def ok_func() -> str:
            return "ok"

        ok_func()
        latencies = metrics.get_latencies("ok_func")
        assert "ok_func" in latencies

    def test_get_counts_all(self) -> None:
        metrics = MetricsCollector()

        @resilient(retry=RetryConfig(max_attempts=1, delay=0.01), listeners=[metrics])
        def func_a() -> str:
            return "a"

        @resilient(retry=RetryConfig(max_attempts=1, delay=0.01), listeners=[metrics])
        def func_b() -> str:
            return "b"

        func_a()
        func_b()
        all_counts = metrics.get_counts()
        assert "func_a" in all_counts
        assert "func_b" in all_counts

    def test_failure_tracking(self) -> None:
        metrics = MetricsCollector()

        @resilient(retry=RetryConfig(max_attempts=1, delay=0.01), listeners=[metrics])
        def fails() -> str:
            raise ValueError("boom")

        with pytest.raises(ValueError):
            fails()

        summary = metrics.summary()
        assert summary["fails"]["success_rate"] == 0.0


class TestMetricsCollectorAsyncSafety:
    @pytest.mark.asyncio
    async def test_concurrent_async_calls_dont_collide(self) -> None:
        """Verify async coroutines don't corrupt latency tracking via thread ID collision."""
        from pyresilience import RetryConfig, resilient

        metrics = MetricsCollector()
        call_count = 0

        @resilient(retry=RetryConfig(max_attempts=1, delay=0), listeners=[metrics])
        async def slow_func() -> str:
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.01)
            return "ok"

        # Run multiple concurrent async calls
        results = await asyncio.gather(slow_func(), slow_func(), slow_func())
        assert all(r == "ok" for r in results)
        assert call_count == 3

        # All 3 calls should have latency tracked
        summary = metrics.summary()
        assert summary["slow_func"]["total_calls"] == 3

    def test_bounded_latencies(self) -> None:
        """Verify latencies are bounded to max 10,000 entries."""
        metrics = MetricsCollector()
        # Directly insert more than 10,000 entries
        for i in range(11000):
            metrics._latencies["test_func"].append(float(i))
        assert len(metrics._latencies["test_func"]) == 10000
        # Oldest entries should be evicted
        assert metrics._latencies["test_func"][0] == 1000.0


class TestLoggingLatencyTracking:
    def test_latency_tracked_on_retry_then_success(self) -> None:
        """Latency tracking works with retry+success."""
        metrics = MetricsCollector()
        call_count = 0

        @resilient(
            retry=RetryConfig(max_attempts=3, delay=0.01),
            listeners=[metrics],
        )
        def retry_then_succeed() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("fail")
            return "ok"

        retry_then_succeed()
        latencies = metrics.get_latencies()
        assert len(latencies) > 0


class TestMetricsCollectorCallIdDefault:
    def test_metrics_without_executor_skips_latency(self) -> None:
        """Calling MetricsCollector directly (call_id=-1) skips latency tracking."""
        metrics = MetricsCollector()
        event = ResilienceEvent(
            event_type=EventType.SUCCESS,
            function_name="manual_func",
            attempt=1,
        )
        metrics(event)
        counts = metrics.get_counts("manual_func")
        assert counts["manual_func"]["success"] == 1
        # No latency should be tracked since call_id was never set
        latencies = metrics.get_latencies("manual_func")
        assert len(latencies.get("manual_func", [])) == 0


class TestJsonEventLoggerNoAttempt:
    def test_event_without_attempt(self, caplog: pytest.LogCaptureFixture) -> None:
        """Event with attempt=0 omits attempt from JSON."""
        logger = JsonEventLogger()

        with caplog.at_level(logging.INFO, logger="pyresilience"):
            event = ResilienceEvent(
                event_type=EventType.CIRCUIT_OPEN,
                function_name="test_func",
                attempt=0,
            )
            logger(event)

        data = json.loads(caplog.records[0].message)
        assert "attempt" not in data


class TestOrjsonDumps:
    def test_make_dumps_produces_valid_json(self) -> None:
        """Verify _make_dumps (orjson or stdlib) produces valid JSON."""
        from pyresilience._logging import _dumps

        result = _dumps({"key": "value", "num": 42})
        parsed = json.loads(result)
        assert parsed["key"] == "value"
        assert parsed["num"] == 42
