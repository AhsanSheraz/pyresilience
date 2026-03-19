"""Prometheus metrics integration for pyresilience.

Requires: ``pip install prometheus-client``

Usage::

    from pyresilience.contrib.prometheus import PrometheusListener
    from pyresilience import resilient, RetryConfig

    prom_listener = PrometheusListener()

    @resilient(retry=RetryConfig(), listeners=[prom_listener])
    def call_api():
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyresilience._types import ResilienceEvent

try:
    from prometheus_client import Counter, Histogram

    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False


class PrometheusListener:
    """A ResilienceListener that exports Prometheus metrics.

    Tracks:
    - ``pyresilience_events_total``: Counter of events by type and function
    - ``pyresilience_call_duration_seconds``: Histogram of call durations

    Requires ``prometheus-client`` to be installed. Raises ``ImportError`` at
    instantiation time if not available.

    Args:
        namespace: Prometheus metric namespace. Defaults to "pyresilience".
        subsystem: Prometheus metric subsystem. Defaults to empty string.
    """

    __slots__ = ("_duration_histogram", "_event_counter")

    def __init__(
        self,
        namespace: str = "pyresilience",
        subsystem: str = "",
    ) -> None:
        if not _HAS_PROMETHEUS:
            raise ImportError(
                "prometheus-client is required for PrometheusListener. "
                "Install with: pip install prometheus-client"
            )
        self._event_counter: Any = Counter(
            f"{namespace}_events_total",
            "Total resilience events",
            ["event_type", "function_name"],
            subsystem=subsystem,
        )
        self._duration_histogram: Any = Histogram(
            f"{namespace}_call_duration_seconds",
            "Call duration in seconds",
            ["function_name"],
            subsystem=subsystem,
        )

    def __call__(self, event: ResilienceEvent) -> None:
        """Process a resilience event and update metrics.

        Args:
            event: The resilience event to record.
        """
        self._event_counter.labels(
            event_type=event.event_type.value,
            function_name=event.function_name,
        ).inc()

        if event.duration is not None:
            self._duration_histogram.labels(
                function_name=event.function_name,
            ).observe(event.duration)
