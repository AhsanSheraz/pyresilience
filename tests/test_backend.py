"""Tests for state backends: InMemoryBackend and the duck-typed RedisBackend."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

import pytest

from pyresilience import InMemoryBackend, StateBackend
from pyresilience.contrib.redis import RedisBackend


class FakeRedis:
    """Minimal stand-in for a redis-py client: stores bytes, records expiries."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.expiry_ms: dict[str, int] = {}

    def get(self, key: str) -> Optional[bytes]:
        return self.data.get(key)

    def set(self, key: str, value: str, px: Optional[int] = None) -> None:
        self.data[key] = value.encode("utf-8")
        if px is not None:
            self.expiry_ms[key] = px

    def incrbyfloat(self, key: str, amount: float) -> float:
        total = float(self.data.get(key, b"0")) + amount
        self.data[key] = repr(total).encode("utf-8")
        return total

    def pexpire(self, key: str, milliseconds: int) -> None:
        self.expiry_ms[key] = milliseconds

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


class FakePipeline:
    """Queues commands and runs them in one ``execute()``, like a redis-py pipeline."""

    def __init__(self, client: PipelineRedis) -> None:
        self.client = client
        self.commands: list[tuple[str, tuple[Any, ...]]] = []

    def incrbyfloat(self, key: str, amount: float) -> FakePipeline:
        self.commands.append(("incrbyfloat", (key, amount)))
        return self

    def pexpire(self, key: str, milliseconds: int) -> FakePipeline:
        self.commands.append(("pexpire", (key, milliseconds)))
        return self

    def execute(self) -> list[Any]:
        self.client.round_trips += 1
        return [getattr(FakeRedis, name)(self.client, *args) for name, args in self.commands]


class PipelineRedis(FakeRedis):
    """A client with pipelines that counts round trips."""

    def __init__(self) -> None:
        super().__init__()
        self.round_trips = 0
        self.transactions: list[bool] = []

    def incrbyfloat(self, key: str, amount: float) -> float:
        self.round_trips += 1
        return super().incrbyfloat(key, amount)

    def pexpire(self, key: str, milliseconds: int) -> None:
        self.round_trips += 1
        super().pexpire(key, milliseconds)

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        self.transactions.append(transaction)
        return FakePipeline(self)


class TestInMemoryBackend:
    def test_get_missing_key(self) -> None:
        assert InMemoryBackend().get("missing") is None

    def test_set_and_get(self) -> None:
        backend = InMemoryBackend()
        backend.set("key", "value")
        assert backend.get("key") == "value"

    def test_delete(self) -> None:
        backend = InMemoryBackend()
        backend.set("key", "value")
        backend.delete("key")
        backend.delete("key")  # deleting a missing key is fine
        assert backend.get("key") is None

    def test_incr_starts_at_zero_and_accumulates(self) -> None:
        backend = InMemoryBackend()
        assert backend.incr("counter", 2.0) == 2.0
        assert backend.incr("counter", 1.5) == 3.5
        assert backend.incr("counter", -3.5) == 0.0
        assert backend.get("counter") == "0.0"

    def test_set_with_ttl_expires(self) -> None:
        backend = InMemoryBackend()
        backend.set("key", "value", ttl=0.05)
        assert backend.get("key") == "value"
        time.sleep(0.1)
        assert backend.get("key") is None

    def test_incr_with_ttl_restarts_after_expiry(self) -> None:
        backend = InMemoryBackend()
        assert backend.incr("counter", 5.0, ttl=0.05) == 5.0
        time.sleep(0.1)
        assert backend.incr("counter", 1.0, ttl=0.05) == 1.0

    def test_incr_without_ttl_keeps_the_existing_expiry(self) -> None:
        backend = InMemoryBackend()
        backend.incr("counter", 5.0, ttl=0.05)
        backend.incr("counter", 1.0)
        time.sleep(0.1)
        assert backend.get("counter") is None

    def test_keys_lists_only_live_keys(self) -> None:
        backend = InMemoryBackend()
        backend.set("stays", "1")
        backend.set("goes", "1", ttl=0.05)
        time.sleep(0.1)
        assert backend.keys() == ["stays"]

    def test_expired_counters_are_dropped_without_being_read(self) -> None:
        backend = InMemoryBackend()
        backend.set("stays", "1")
        for index in range(300):
            backend.incr(f"old:{index}", 1.0, ttl=0.01)
        time.sleep(0.1)
        # Nothing reads the old keys again; writing new ones clears them out
        for index in range(300):
            backend.incr(f"new:{index}", 1.0, ttl=60.0)
        assert len(backend._data) == 301
        assert backend.get("stays") == "1"
        assert backend.get("new:0") == "1.0"

    def test_expired_values_are_dropped_without_being_read(self) -> None:
        backend = InMemoryBackend()
        for index in range(300):
            backend.set(f"old:{index}", "x", ttl=0.01)
        time.sleep(0.1)
        for index in range(300):
            backend.set(f"new:{index}", "y", ttl=60.0)
        assert len(backend._data) == 300
        assert backend.get("new:299") == "y"

    def test_incr_is_atomic_across_threads(self) -> None:
        backend = InMemoryBackend()

        def worker() -> None:
            for _ in range(500):
                backend.incr("counter", 1.0)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert backend.get("counter") == "4000.0"

    def test_satisfies_the_backend_protocol(self) -> None:
        assert isinstance(InMemoryBackend(), StateBackend)

    def test_incomplete_object_is_not_a_backend(self) -> None:
        class GetOnly:
            def get(self, key: str) -> Any:
                return None

        assert not isinstance(GetOnly(), StateBackend)


class TestRedisBackend:
    def test_satisfies_the_backend_protocol(self) -> None:
        assert isinstance(RedisBackend(FakeRedis()), StateBackend)

    def test_keys_are_prefixed(self) -> None:
        client = FakeRedis()
        RedisBackend(client).set("svc:cb:open", "1")
        assert list(client.data) == ["pyresilience:svc:cb:open"]

    def test_custom_prefix(self) -> None:
        client = FakeRedis()
        RedisBackend(client, prefix="myapp:").set("key", "1")
        assert list(client.data) == ["myapp:key"]

    def test_get_decodes_bytes(self) -> None:
        backend = RedisBackend(FakeRedis())
        backend.set("key", "value")
        assert backend.get("key") == "value"

    def test_get_missing_key(self) -> None:
        assert RedisBackend(FakeRedis()).get("missing") is None

    def test_get_accepts_decoded_clients(self) -> None:
        class DecodingRedis(FakeRedis):
            def get(self, key: str) -> Any:
                value = super().get(key)
                return value.decode("utf-8") if value is not None else None

        backend = RedisBackend(DecodingRedis())
        backend.set("key", "value")
        assert backend.get("key") == "value"

    def test_set_with_ttl_uses_milliseconds(self) -> None:
        client = FakeRedis()
        RedisBackend(client).set("key", "value", ttl=1.5)
        assert client.expiry_ms["pyresilience:key"] == 1500

    def test_set_without_ttl_sets_no_expiry(self) -> None:
        client = FakeRedis()
        RedisBackend(client).set("key", "value")
        assert client.expiry_ms == {}

    def test_incr_returns_the_running_total(self) -> None:
        backend = RedisBackend(FakeRedis())
        assert backend.incr("counter", 2.0) == 2.0
        assert backend.incr("counter", 0.5) == 2.5

    def test_incr_with_ttl_refreshes_the_expiry(self) -> None:
        client = FakeRedis()
        RedisBackend(client).incr("counter", 1.0, ttl=120.0)
        assert client.expiry_ms["pyresilience:counter"] == 120_000

    def test_incr_without_ttl_sets_no_expiry(self) -> None:
        client = FakeRedis()
        RedisBackend(client).incr("counter", 1.0)
        assert client.expiry_ms == {}

    def test_incr_with_ttl_is_one_round_trip_with_a_pipeline(self) -> None:
        client = PipelineRedis()
        backend = RedisBackend(client)
        assert backend.incr("counter", 2.0, ttl=120.0) == 2.0
        assert backend.incr("counter", 0.5, ttl=120.0) == 2.5
        assert client.round_trips == 2
        assert client.expiry_ms["pyresilience:counter"] == 120_000
        # No MULTI/EXEC around the two commands
        assert client.transactions == [False, False]

    def test_incr_without_ttl_needs_no_pipeline(self) -> None:
        client = PipelineRedis()
        assert RedisBackend(client).incr("counter", 1.0) == 1.0
        assert client.round_trips == 1
        assert client.transactions == []

    def test_tiny_ttl_is_at_least_one_millisecond(self) -> None:
        client = FakeRedis()
        backend = RedisBackend(client)
        backend.set("a", "1", ttl=0.0001)
        backend.incr("b", 1.0, ttl=0.0001)
        assert client.expiry_ms == {"pyresilience:a": 1, "pyresilience:b": 1}

    def test_delete(self) -> None:
        client = FakeRedis()
        backend = RedisBackend(client)
        backend.set("key", "value")
        backend.delete("key")
        assert client.data == {}

    def test_module_does_not_import_a_redis_library(self) -> None:
        from pathlib import Path

        from pyresilience.contrib import redis as redis_module

        source = Path(redis_module.__file__).read_text(encoding="utf-8")
        # Only the docstring example mentions the import; the module itself has none
        code = source.split('"""', 2)[2]
        assert "import redis" not in code
        assert "from redis" not in code

    def test_errors_from_the_client_propagate(self) -> None:
        class DownRedis(FakeRedis):
            def get(self, key: str) -> Any:
                raise ConnectionError("redis is down")

        with pytest.raises(ConnectionError):
            RedisBackend(DownRedis()).get("key")
