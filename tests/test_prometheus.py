"""Tests for Prometheus listener integration."""

from __future__ import annotations

import sys
import types
from typing import Any, ClassVar

import pytest

from pyresilience._types import EventType, ResilienceEvent


class TestPrometheusListenerMissing:
    """Tests when prometheus_client is NOT installed."""

    def test_raises_import_error_without_prometheus(self) -> None:
        from pyresilience.contrib.prometheus import PrometheusListener

        with pytest.raises(ImportError, match="prometheus-client is required"):
            PrometheusListener()


class _FakeLabelWrapper:
    """Simulates the label wrapper returned by .labels()."""

    def __init__(self) -> None:
        self.value = 0.0

    def inc(self, amount: float = 1.0) -> None:
        self.value += amount

    def observe(self, value: float) -> None:
        self.value = value


class _FakeCounter:
    """Simulates prometheus_client.Counter."""

    instances: ClassVar[list[_FakeCounter]] = []

    def __init__(self, name: str, doc: str, labels: list[str], **kwargs: object) -> None:
        self.name = name
        self.doc = doc
        self.label_names = labels
        self._label_wrappers: dict[tuple[str, ...], _FakeLabelWrapper] = {}
        _FakeCounter.instances.append(self)

    def labels(self, **kwargs: str) -> _FakeLabelWrapper:
        key = tuple(sorted(kwargs.items()))
        if key not in self._label_wrappers:
            self._label_wrappers[key] = _FakeLabelWrapper()
        return self._label_wrappers[key]


class _FakeHistogram:
    """Simulates prometheus_client.Histogram."""

    instances: ClassVar[list[_FakeHistogram]] = []

    def __init__(self, name: str, doc: str, labels: list[str], **kwargs: object) -> None:
        self.name = name
        self.doc = doc
        self.label_names = labels
        self._label_wrappers: dict[tuple[str, ...], _FakeLabelWrapper] = {}
        _FakeHistogram.instances.append(self)

    def labels(self, **kwargs: str) -> _FakeLabelWrapper:
        key = tuple(sorted(kwargs.items()))
        if key not in self._label_wrappers:
            self._label_wrappers[key] = _FakeLabelWrapper()
        return self._label_wrappers[key]


class TestPrometheusListenerWithMock:
    """Tests with a mocked prometheus_client module."""

    def _install_mock_prometheus(self) -> tuple[Any, Any]:
        """Install a mock prometheus_client module and reload contrib module."""
        _FakeCounter.instances = []
        _FakeHistogram.instances = []

        prom_mod = types.ModuleType("prometheus_client")
        prom_mod.Counter = _FakeCounter  # type: ignore[attr-defined]
        prom_mod.Histogram = _FakeHistogram  # type: ignore[attr-defined]
        sys.modules["prometheus_client"] = prom_mod

        import importlib

        import pyresilience.contrib.prometheus as prom_contrib

        importlib.reload(prom_contrib)

        return _FakeCounter, _FakeHistogram

    def _uninstall_mock_prometheus(self) -> None:
        """Remove mock prometheus_client and reload contrib module."""
        sys.modules.pop("prometheus_client", None)

        import importlib

        import pyresilience.contrib.prometheus as prom_contrib

        importlib.reload(prom_contrib)

    def test_instantiation_with_prometheus(self) -> None:
        fake_counter, fake_histogram = self._install_mock_prometheus()
        try:
            from pyresilience.contrib.prometheus import PrometheusListener

            listener = PrometheusListener()
            assert listener is not None
            assert len(fake_counter.instances) == 1
            assert len(fake_histogram.instances) == 1
            assert fake_counter.instances[0].name == "pyresilience_events_total"
            assert fake_histogram.instances[0].name == "pyresilience_call_duration_seconds"
        finally:
            self._uninstall_mock_prometheus()

    def test_custom_namespace(self) -> None:
        fake_counter, fake_histogram = self._install_mock_prometheus()
        try:
            from pyresilience.contrib.prometheus import PrometheusListener

            PrometheusListener(namespace="myapp")
            assert fake_counter.instances[0].name == "myapp_events_total"
            assert fake_histogram.instances[0].name == "myapp_call_duration_seconds"
        finally:
            self._uninstall_mock_prometheus()

    def test_call_increments_counter(self) -> None:
        fake_counter, _fake_histogram = self._install_mock_prometheus()
        try:
            from pyresilience.contrib.prometheus import PrometheusListener

            listener = PrometheusListener()
            event = ResilienceEvent(
                event_type=EventType.RETRY,
                function_name="my_func",
                attempt=2,
            )
            listener(event)

            counter = fake_counter.instances[0]
            key = tuple(sorted({"event_type": "retry", "function_name": "my_func"}.items()))
            wrapper = counter._label_wrappers[key]
            assert wrapper.value == 1.0
        finally:
            self._uninstall_mock_prometheus()

    def test_multiple_events_increment_counter(self) -> None:
        fake_counter, _fake_histogram = self._install_mock_prometheus()
        try:
            from pyresilience.contrib.prometheus import PrometheusListener

            listener = PrometheusListener()

            for _ in range(5):
                event = ResilienceEvent(
                    event_type=EventType.SUCCESS,
                    function_name="api_call",
                    attempt=1,
                )
                listener(event)

            counter = fake_counter.instances[0]
            key = tuple(sorted({"event_type": "success", "function_name": "api_call"}.items()))
            wrapper = counter._label_wrappers[key]
            assert wrapper.value == 5.0
        finally:
            self._uninstall_mock_prometheus()

    def test_different_event_types_tracked_separately(self) -> None:
        fake_counter, _fake_histogram = self._install_mock_prometheus()
        try:
            from pyresilience.contrib.prometheus import PrometheusListener

            listener = PrometheusListener()

            listener(
                ResilienceEvent(
                    event_type=EventType.SUCCESS,
                    function_name="my_func",
                    attempt=1,
                )
            )
            listener(
                ResilienceEvent(
                    event_type=EventType.RETRY,
                    function_name="my_func",
                    attempt=2,
                )
            )

            counter = fake_counter.instances[0]
            success_key = tuple(
                sorted({"event_type": "success", "function_name": "my_func"}.items())
            )
            retry_key = tuple(sorted({"event_type": "retry", "function_name": "my_func"}.items()))
            assert counter._label_wrappers[success_key].value == 1.0
            assert counter._label_wrappers[retry_key].value == 1.0
        finally:
            self._uninstall_mock_prometheus()

    def test_histogram_observes_duration_on_success(self) -> None:
        _fake_counter, fake_histogram = self._install_mock_prometheus()
        try:
            from pyresilience.contrib.prometheus import PrometheusListener

            listener = PrometheusListener()
            event = ResilienceEvent(
                event_type=EventType.SUCCESS,
                function_name="api_call",
                attempt=1,
                duration=0.123,
            )
            listener(event)

            histogram = fake_histogram.instances[0]
            key = tuple(sorted({"function_name": "api_call"}.items()))
            wrapper = histogram._label_wrappers[key]
            assert wrapper.value == 0.123
        finally:
            self._uninstall_mock_prometheus()

    def test_histogram_not_observed_without_duration(self) -> None:
        _fake_counter, fake_histogram = self._install_mock_prometheus()
        try:
            from pyresilience.contrib.prometheus import PrometheusListener

            listener = PrometheusListener()
            event = ResilienceEvent(
                event_type=EventType.RETRY,
                function_name="api_call",
                attempt=2,
            )
            listener(event)

            histogram = fake_histogram.instances[0]
            assert len(histogram._label_wrappers) == 0
        finally:
            self._uninstall_mock_prometheus()
