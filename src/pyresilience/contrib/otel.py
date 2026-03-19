"""OpenTelemetry integration for pyresilience.

Requires: ``pip install opentelemetry-api opentelemetry-sdk``

Usage::

    from pyresilience.contrib.otel import OpenTelemetryListener
    from pyresilience import resilient, RetryConfig

    otel_listener = OpenTelemetryListener()

    @resilient(retry=RetryConfig(), listeners=[otel_listener])
    def call_api():
        ...
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pyresilience._types import ResilienceEvent

try:
    from opentelemetry import trace

    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False


class OpenTelemetryListener:
    """A ResilienceListener that emits OpenTelemetry span events.

    Records resilience events (retries, circuit breaker state changes, timeouts, etc.)
    as events on the current active span. If no active span exists, events are silently
    dropped.

    Requires ``opentelemetry-api`` to be installed. Raises ``ImportError`` at
    instantiation time if not available.

    Args:
        tracer_name: Name of the tracer to use. Defaults to "pyresilience".
    """

    __slots__ = ("_tracer",)

    def __init__(self, tracer_name: str = "pyresilience") -> None:
        if not _HAS_OTEL:
            raise ImportError(
                "opentelemetry-api is required for OpenTelemetryListener. "
                "Install with: pip install opentelemetry-api opentelemetry-sdk"
            )
        self._tracer = trace.get_tracer(tracer_name)

    def __call__(self, event: ResilienceEvent) -> None:
        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return

        attributes: dict[str, Any] = {
            "pyresilience.event": event.event_type.value,
            "pyresilience.function": event.function_name,
        }
        if event.attempt:
            attributes["pyresilience.attempt"] = event.attempt
        if event.error is not None:
            attributes["pyresilience.error_type"] = type(event.error).__name__
            attributes["pyresilience.error_message"] = str(event.error)
        if event.detail:
            attributes["pyresilience.detail"] = event.detail

        span.add_event(
            name=f"pyresilience.{event.event_type.value}",
            attributes=attributes,
        )
