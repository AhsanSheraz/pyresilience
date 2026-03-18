"""Structured JSON event logging with orjson (Rust-based) or stdlib json fallback."""

from __future__ import annotations

import importlib.util
import json as _stdlib_json
import logging
import time
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from pyresilience._types import ResilienceEvent

logger = logging.getLogger("pyresilience")


def _dumps(obj: Any) -> str:
    """Serialize to JSON using orjson if available, else stdlib json."""
    if importlib.util.find_spec("orjson") is not None:
        import orjson  # type: ignore[import-not-found]

        return str(orjson.dumps(obj).decode("utf-8"))
    return _stdlib_json.dumps(obj, default=str)


def _event_to_dict(event: ResilienceEvent) -> dict[str, Any]:
    """Convert a ResilienceEvent to a JSON-serializable dict."""
    d: dict[str, Any] = {
        "event": event.event_type.value,
        "function": event.function_name,
        "timestamp": time.time(),
    }
    if event.attempt:
        d["attempt"] = event.attempt
    if event.error is not None:
        d["error_type"] = type(event.error).__name__
        d["error_message"] = str(event.error)
    if event.detail:
        d["detail"] = event.detail
    return d


class JsonEventLogger:
    """A ResilienceListener that emits structured JSON log lines.

    Uses orjson (Rust-based) if installed for ~10x faster serialization,
    falls back to stdlib json automatically.

    Usage::

        from pyresilience import resilient, RetryConfig
        from pyresilience.logging import JsonEventLogger

        logger = JsonEventLogger()

        @resilient(retry=RetryConfig(), listeners=[logger])
        def my_func():
            ...
    """

    def __init__(
        self,
        logger_name: str = "pyresilience",
        level: int = logging.INFO,
        include_timestamp: bool = True,
    ) -> None:
        self._logger = logging.getLogger(logger_name)
        self._level = level
        self._include_timestamp = include_timestamp

    def __call__(self, event: ResilienceEvent) -> None:
        d = _event_to_dict(event)
        if not self._include_timestamp:
            d.pop("timestamp", None)
        self._logger.log(self._level, _dumps(d))


class MetricsCollector:
    """A ResilienceListener that collects metrics in-memory for observability.

    Tracks counts of each event type per function, plus total call latency.
    Useful for exposing to Prometheus, StatsD, or custom dashboards.

    Usage::

        from pyresilience import resilient, RetryConfig
        from pyresilience.logging import MetricsCollector

        metrics = MetricsCollector()

        @resilient(retry=RetryConfig(), listeners=[metrics])
        def my_func():
            ...

        print(metrics.summary())
    """

    def __init__(self) -> None:
        self._counts: dict[str, dict[str, int]] = {}
        self._call_starts: dict[str, float] = {}
        self._latencies: dict[str, list[float]] = {}

    def __call__(self, event: ResilienceEvent) -> None:
        func = event.function_name
        evt = event.event_type.value

        if func not in self._counts:
            self._counts[func] = {}
        self._counts[func][evt] = self._counts[func].get(evt, 0) + 1

        # Track latency from first attempt to success/failure
        if event.attempt == 1 and evt not in ("success", "failure"):
            self._call_starts[func] = time.monotonic()
        if evt in ("success", "failure") and func in self._call_starts:
            latency = time.monotonic() - self._call_starts.pop(func)
            if func not in self._latencies:
                self._latencies[func] = []
            self._latencies[func].append(latency)

    def get_counts(self, function_name: Optional[str] = None) -> dict[str, dict[str, int]]:
        """Get event counts, optionally filtered by function name."""
        if function_name:
            return {function_name: self._counts.get(function_name, {})}
        return dict(self._counts)

    def get_latencies(self, function_name: Optional[str] = None) -> dict[str, list[float]]:
        """Get call latencies, optionally filtered by function name."""
        if function_name:
            return {function_name: self._latencies.get(function_name, [])}
        return dict(self._latencies)

    def summary(self) -> dict[str, Any]:
        """Get a full summary of all metrics."""
        result: dict[str, Any] = {}
        for func, counts in self._counts.items():
            latencies = self._latencies.get(func, [])
            result[func] = {
                "events": dict(counts),
                "total_calls": counts.get("success", 0) + counts.get("failure", 0),
                "success_rate": (
                    counts.get("success", 0)
                    / max(counts.get("success", 0) + counts.get("failure", 0), 1)
                ),
            }
            if latencies:
                result[func]["avg_latency_ms"] = round(sum(latencies) / len(latencies) * 1000, 2)
                result[func]["p99_latency_ms"] = round(
                    sorted(latencies)[int(len(latencies) * 0.99)] * 1000, 2
                )
        return result

    def reset(self) -> None:
        """Reset all collected metrics."""
        self._counts.clear()
        self._call_starts.clear()
        self._latencies.clear()
