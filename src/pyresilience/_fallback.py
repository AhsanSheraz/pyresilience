"""Fallback handling: the plain handler and the alternatives-with-cooldown router."""

from __future__ import annotations

import inspect
import threading
import time
from typing import Any, Callable, Optional, Type

from pyresilience._events import _emit
from pyresilience._exceptions import (
    BulkheadFullError,
    CircuitOpenError,
    RateLimitExceededError,
    ResilienceError,
    ResilienceTimeoutError,
)
from pyresilience._types import EventType, FallbackConfig, ResilienceListener

_monotonic = time.monotonic

# Rejections raised by the executor itself always go to the fallback chain
_REJECTIONS = (CircuitOpenError, RateLimitExceededError, BulkheadFullError)


def _apply_fallback(fallback_cfg: FallbackConfig, exc: BaseException) -> Any:
    """Apply fallback handler or return static fallback value."""
    handler = fallback_cfg.handler
    if callable(handler):
        return handler(exc)
    return handler


async def _apply_fallback_async(fallback_cfg: FallbackConfig, exc: BaseException) -> Any:
    """Apply fallback handler with async support.

    If the handler is an async function, awaits it. Otherwise, calls it synchronously.
    """
    handler = fallback_cfg.handler
    if callable(handler):
        if inspect.iscoroutinefunction(handler):
            return await handler(exc)
        return handler(exc)
    return handler


def _fallback_match(
    exc: BaseException, types: tuple[Type[BaseException], ...]
) -> Optional[BaseException]:
    """Return the error a fallback set up for *types* applies to, or None.

    That is *exc* itself, or, when a spent deadline stopped the retries, the error
    that was being retried: the deadline replaces it with a timeout error, which
    must not hide it from ``fallback_on``.
    """
    if isinstance(exc, types):
        return exc
    if isinstance(exc, ResilienceTimeoutError):
        cause = exc.__cause__
        if cause is not None and isinstance(cause, types):
            return cause
    return None


def _needs_router(config: Optional[FallbackConfig]) -> bool:
    """True when the fallback config asks for alternatives or a usable cooldown."""
    if config is None:
        return False
    return bool(config.alternatives or (config.cooldown > 0 and config.handler is not None))


class _Target:
    """Cooldown state of the primary function or of one alternative."""

    __slots__ = ("cool_until", "failures", "fn", "last_error", "name")

    def __init__(self, name: str, fn: Optional[Callable[..., Any]]) -> None:
        self.name = name
        self.fn = fn
        self.failures = 0
        self.cool_until = 0.0
        self.last_error: Optional[BaseException] = None


class _FallbackRouter:
    """Routes a failing call to alternatives and cools down targets that keep failing.

    Order for every call: the primary function (unless it is cooling down), then each
    alternative that is not cooling down, then the handler. A target enters cooldown
    after ``cooldown_threshold`` consecutive failures and is skipped for ``cooldown``
    seconds. Cooldown never fails a call by itself: when nothing else is available,
    the primary is called anyway.

    Thread-safe; one router can serve a sync and an async executor at the same time.
    """

    __slots__ = (
        "_alternatives",
        "_config",
        "_cooldown",
        "_eligible_types",
        "_has_handler",
        "_ignore_on",
        "_lock",
        "_primary",
        "_threshold",
    )

    def __init__(self, config: FallbackConfig, ignore_on: tuple[Type[BaseException], ...]) -> None:
        self._config = config
        # Executor rejections always reach the fallback chain, as in the plain handler path
        self._eligible_types: tuple[Type[BaseException], ...] = (
            *config.fallback_on,
            *_REJECTIONS,
        )
        self._ignore_on = ignore_on
        self._cooldown = config.cooldown
        self._threshold = config.cooldown_threshold
        self._has_handler = config.handler is not None
        self._primary = _Target("primary", None)
        self._alternatives = [
            _Target(getattr(fn, "__name__", type(fn).__name__), fn) for fn in config.alternatives
        ]
        self._lock = threading.Lock()

    def _eligible(self, exc: BaseException) -> bool:
        if self._ignore_on and isinstance(exc, self._ignore_on):
            return False
        return _fallback_match(exc, self._eligible_types) is not None

    def _handler_error(self, error: BaseException) -> BaseException:
        """The error handed to the handler: the one ``fallback_on`` matched."""
        return _fallback_match(error, self._eligible_types) or error

    def primary_cooling(self) -> bool:
        """True while calls skip the primary function."""
        return self._skip_primary()

    def _skip_primary(self) -> bool:
        """The primary is cooling down and something else can take the call."""
        now = _monotonic()
        if self._primary.cool_until <= now:
            return False
        if self._has_handler:
            return True
        return any(target.cool_until <= now for target in self._alternatives)

    def _record_failure(
        self,
        target: _Target,
        exc: BaseException,
        func_name: str,
        listeners: list[ResilienceListener],
    ) -> None:
        entered = False
        with self._lock:
            now = _monotonic()
            if 0 < target.cool_until <= now:
                # The cooldown ran out: the failure streak starts again
                target.failures = 0
                target.cool_until = 0.0
            target.failures += 1
            target.last_error = exc
            if self._cooldown > 0 and target.failures >= self._threshold:
                entered = target.cool_until <= now
                target.cool_until = now + self._cooldown
        if entered and listeners:
            _emit(
                listeners,
                EventType.COOLDOWN,
                func_name,
                error=exc,
                detail=f"{target.name} cooling down for {self._cooldown}s",
            )

    def _record_success(self, target: _Target) -> None:
        with self._lock:
            target.failures = 0
            target.cool_until = 0.0
            target.last_error = None

    def _cooldown_error(self) -> BaseException:
        """The failure that put the primary into cooldown."""
        error = self._primary.last_error
        if error is None:  # pragma: no cover - a cooling target always has an error
            error = ResilienceError("primary is cooling down")
        return error

    def state(self) -> dict[str, dict[str, Any]]:
        """Snapshot per target: consecutive failures and remaining cooldown seconds."""
        now = _monotonic()
        with self._lock:
            return {
                target.name: {
                    "failures": target.failures,
                    "cooling_for": max(0.0, target.cool_until - now),
                }
                for target in [self._primary, *self._alternatives]
            }

    def run_sync(
        self,
        primary_call: Callable[..., Any],
        func: Callable[..., Any],
        func_name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        listeners: list[ResilienceListener],
        on_primary_skipped: Optional[Callable[[], None]] = None,
    ) -> Any:
        """Run one call.

        *on_primary_skipped* is called right before an alternative or the handler
        answers a call for which the primary was not called at all.
        """
        primary = self._primary
        error: BaseException
        skipped = self._skip_primary()
        if skipped:
            error = self._cooldown_error()
        else:
            try:
                result = primary_call(func, func_name, *args, **kwargs)
            except Exception as exc:
                if not self._eligible(exc):
                    raise
                self._record_failure(primary, exc, func_name, listeners)
                error = exc
            else:
                if primary.failures:
                    self._record_success(primary)
                return result

        for target in self._alternatives:
            if target.cool_until > _monotonic():
                continue
            try:
                result = target.fn(*args, **kwargs)  # type: ignore[misc]
            except Exception as exc:
                if not self._eligible(exc):
                    raise
                self._record_failure(target, exc, func_name, listeners)
                error = exc
                continue
            if inspect.isawaitable(result):
                # A sync call cannot await it; fail loudly instead of returning a coroutine
                close = getattr(result, "close", None)
                if close is not None:
                    close()
                raise TypeError(
                    f"alternative {target.name} returned an awaitable; "
                    "a sync function needs sync alternatives"
                )
            if target.failures:
                self._record_success(target)
            if skipped and on_primary_skipped is not None:
                on_primary_skipped()
            if listeners:
                _emit(
                    listeners,
                    EventType.FALLBACK_USED,
                    func_name,
                    error=error,
                    detail=f"alternative {target.name}",
                )
            return result

        if self._has_handler:
            if skipped and on_primary_skipped is not None:
                on_primary_skipped()
            if listeners:
                _emit(listeners, EventType.FALLBACK_USED, func_name, error=error)
            return _apply_fallback(self._config, self._handler_error(error))
        if skipped:
            # Nothing else could take the call after all: a cooldown never fails a call
            # by itself, so the primary is called
            try:
                result = primary_call(func, func_name, *args, **kwargs)
            except Exception as exc:
                if self._eligible(exc):
                    self._record_failure(primary, exc, func_name, listeners)
                raise
            self._record_success(primary)
            return result
        raise error

    async def run_async(
        self,
        primary_call: Callable[..., Any],
        func: Callable[..., Any],
        func_name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        listeners: list[ResilienceListener],
        on_primary_skipped: Optional[Callable[[], None]] = None,
    ) -> Any:
        """Async twin of ``run_sync``."""
        primary = self._primary
        error: BaseException
        skipped = self._skip_primary()
        if skipped:
            error = self._cooldown_error()
        else:
            try:
                result = await primary_call(func, func_name, *args, **kwargs)
            except Exception as exc:
                if not self._eligible(exc):
                    raise
                self._record_failure(primary, exc, func_name, listeners)
                error = exc
            else:
                if primary.failures:
                    self._record_success(primary)
                return result

        for target in self._alternatives:
            if target.cool_until > _monotonic():
                continue
            try:
                result = target.fn(*args, **kwargs)  # type: ignore[misc]
                if inspect.isawaitable(result):
                    result = await result
            except Exception as exc:
                if not self._eligible(exc):
                    raise
                self._record_failure(target, exc, func_name, listeners)
                error = exc
                continue
            if target.failures:
                self._record_success(target)
            if skipped and on_primary_skipped is not None:
                on_primary_skipped()
            if listeners:
                _emit(
                    listeners,
                    EventType.FALLBACK_USED,
                    func_name,
                    error=error,
                    detail=f"alternative {target.name}",
                )
            return result

        if self._has_handler:
            if skipped and on_primary_skipped is not None:
                on_primary_skipped()
            if listeners:
                _emit(listeners, EventType.FALLBACK_USED, func_name, error=error)
            return await _apply_fallback_async(self._config, self._handler_error(error))
        if skipped:
            # Nothing else could take the call after all: a cooldown never fails a call
            # by itself, so the primary is called
            try:
                result = await primary_call(func, func_name, *args, **kwargs)
            except Exception as exc:
                if self._eligible(exc):
                    self._record_failure(primary, exc, func_name, listeners)
                raise
            self._record_success(primary)
            return result
        raise error
