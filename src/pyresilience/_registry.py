"""Registry — centralized management of named resilience instances."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar

if TYPE_CHECKING:
    from pyresilience._types import ResilienceConfig

F = TypeVar("F", bound=Callable[..., Any])


class ResilienceRegistry:
    """Centralized registry for named resilience configurations.

    Allows sharing circuit breaker state, rate limiters, and other
    resilience components across multiple decorated functions.

    Usage::

        registry = ResilienceRegistry()
        registry.register("payment-api", ResilienceConfig(
            retry=RetryConfig(max_attempts=3),
            circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
        ))

        @registry.decorator("payment-api")
        async def charge_card(amount: float) -> dict: ...

        @registry.decorator("payment-api")
        async def refund_card(amount: float) -> dict: ...

        # Both functions share the same circuit breaker state
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._configs: dict[str, ResilienceConfig] = {}
        self._executors: dict[str, Any] = {}
        self._default_config: Optional[ResilienceConfig] = None

    def set_default(self, config: ResilienceConfig) -> None:
        """Set a default config used when a name is not registered."""
        with self._lock:
            self._default_config = config

    def register(self, name: str, config: ResilienceConfig) -> None:
        """Register a named resilience configuration."""
        with self._lock:
            self._configs[name] = config
            # Clear cached executor so it's rebuilt with new config
            self._executors.pop(name, None)

    def get(self, name: str) -> Optional[ResilienceConfig]:
        """Get a registered config by name. Returns None if not found."""
        with self._lock:
            return self._configs.get(name)

    def get_or_default(self, name: str) -> ResilienceConfig:
        """Get a registered config, falling back to default."""
        with self._lock:
            config = self._configs.get(name)
            if config is not None:
                return config
            if self._default_config is not None:
                return self._default_config
            raise KeyError(f"No config registered for '{name}' and no default set")

    def _get_executor(self, name: str, is_async: bool) -> Any:
        """Get or create a cached executor for a named config."""
        key = f"{name}:{'async' if is_async else 'sync'}"
        with self._lock:
            if key in self._executors:
                return self._executors[key]

            config = self._configs.get(name)
            if config is None:
                config = self._default_config
            if config is None:
                raise KeyError(f"No config registered for '{name}' and no default set")

            if is_async:
                from pyresilience._executor import _AsyncExecutor

                result: Any = _AsyncExecutor(config)
            else:
                from pyresilience._executor import _SyncExecutor

                result = _SyncExecutor(config)

            self._executors[key] = result
            return result

    def decorator(self, name: str) -> Callable[[F], F]:
        """Create a decorator that applies the named resilience config.

        Multiple functions decorated with the same name share the same
        circuit breaker, rate limiter, and other stateful components.
        """
        import functools
        import inspect

        def wrapper(func: F) -> F:
            if inspect.iscoroutinefunction(func):
                executor = self._get_executor(name, is_async=True)

                fn_name = func.__name__

                @functools.wraps(func)
                async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
                    return await executor.execute(func, fn_name, *args, **kwargs)

                return async_wrapped  # type: ignore[return-value]
            else:
                executor = self._get_executor(name, is_async=False)
                fn_name = func.__name__

                @functools.wraps(func)
                def sync_wrapped(*args: Any, **kwargs: Any) -> Any:
                    return executor.execute(func, fn_name, *args, **kwargs)

                return sync_wrapped  # type: ignore[return-value]

        return wrapper

    @property
    def names(self) -> list[str]:
        """List all registered config names."""
        with self._lock:
            return list(self._configs.keys())

    def unregister(self, name: str) -> bool:
        """Remove a named config. Returns True if it existed."""
        with self._lock:
            existed = name in self._configs
            self._configs.pop(name, None)
            # Also remove cached executors
            self._executors.pop(f"{name}:async", None)
            self._executors.pop(f"{name}:sync", None)
            return existed

    def clear(self) -> None:
        """Remove all registered configs and cached executors."""
        with self._lock:
            self._configs.clear()
            self._executors.clear()
            self._default_config = None
