"""Event emission shared by the executors and the pattern helpers."""

from __future__ import annotations

import logging
from typing import Optional

from pyresilience._logging import resilience_context
from pyresilience._types import EventType, ResilienceEvent, ResilienceListener

# Module-level logger for listener error reporting
_logger = logging.getLogger("pyresilience")


def _emit(
    listeners: list[ResilienceListener],
    event_type: EventType,
    func_name: str,
    attempt: int = 0,
    error: Optional[BaseException] = None,
    detail: str = "",
    duration: Optional[float] = None,
) -> None:
    """Emit an event to all listeners. No-op when listeners list is empty."""
    ctx = resilience_context.get()
    event = ResilienceEvent(
        event_type=event_type,
        function_name=func_name,
        attempt=attempt,
        error=error,
        detail=detail,
        context=ctx if ctx else None,
        duration=duration,
    )
    for listener in listeners:
        try:
            listener(event)
        except Exception:
            _logger.warning("Listener %r raised an exception", listener, exc_info=True)
