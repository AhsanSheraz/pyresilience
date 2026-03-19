"""Tests for OpenTelemetry listener integration."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from pyresilience._types import EventType, ResilienceEvent


class TestOpenTelemetryListenerMissing:
    """Tests when opentelemetry is NOT installed."""

    def test_raises_import_error_without_otel(self) -> None:
        from pyresilience.contrib.otel import OpenTelemetryListener

        with pytest.raises(ImportError, match="opentelemetry-api is required"):
            OpenTelemetryListener()


class TestOpenTelemetryListenerWithMock:
    """Tests with a mocked opentelemetry module."""

    def _install_mock_otel(self) -> tuple[MagicMock, MagicMock]:
        """Install a mock opentelemetry module and reload otel contrib."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        mock_trace = MagicMock()
        mock_trace.get_current_span.return_value = mock_span
        mock_tracer = MagicMock()
        mock_trace.get_tracer.return_value = mock_tracer

        # Create a fake opentelemetry package
        otel_pkg = types.ModuleType("opentelemetry")
        otel_trace = types.ModuleType("opentelemetry.trace")
        otel_trace.get_tracer = mock_trace.get_tracer  # type: ignore[attr-defined]
        otel_trace.get_current_span = mock_trace.get_current_span  # type: ignore[attr-defined]
        otel_pkg.trace = otel_trace  # type: ignore[attr-defined]

        sys.modules["opentelemetry"] = otel_pkg
        sys.modules["opentelemetry.trace"] = otel_trace

        # Reload the otel contrib module so it picks up the mock
        import importlib

        import pyresilience.contrib.otel as otel_mod

        importlib.reload(otel_mod)

        return mock_span, mock_trace

    def _uninstall_mock_otel(self) -> None:
        """Remove mock opentelemetry and reload otel contrib."""
        sys.modules.pop("opentelemetry", None)
        sys.modules.pop("opentelemetry.trace", None)

        import importlib

        import pyresilience.contrib.otel as otel_mod

        importlib.reload(otel_mod)

    def test_instantiation_with_otel(self) -> None:
        _mock_span, mock_trace = self._install_mock_otel()
        try:
            from pyresilience.contrib.otel import OpenTelemetryListener

            listener = OpenTelemetryListener()
            assert listener is not None
            mock_trace.get_tracer.assert_called_once_with("pyresilience")
        finally:
            self._uninstall_mock_otel()

    def test_custom_tracer_name(self) -> None:
        _mock_span, mock_trace = self._install_mock_otel()
        try:
            from pyresilience.contrib.otel import OpenTelemetryListener

            OpenTelemetryListener(tracer_name="my-app")
            mock_trace.get_tracer.assert_called_with("my-app")
        finally:
            self._uninstall_mock_otel()

    def test_call_emits_span_event(self) -> None:
        mock_span, _mock_trace = self._install_mock_otel()
        try:
            from pyresilience.contrib.otel import OpenTelemetryListener

            listener = OpenTelemetryListener()
            event = ResilienceEvent(
                event_type=EventType.RETRY,
                function_name="my_func",
                attempt=2,
                error=ValueError("connection refused"),
                detail="retrying in 1.00s",
            )
            listener(event)

            mock_span.add_event.assert_called_once()
            call_kwargs = mock_span.add_event.call_args
            assert call_kwargs[1]["name"] == "pyresilience.retry"
            attrs = call_kwargs[1]["attributes"]
            assert attrs["pyresilience.event"] == "retry"
            assert attrs["pyresilience.function"] == "my_func"
            assert attrs["pyresilience.attempt"] == 2
            assert attrs["pyresilience.error_type"] == "ValueError"
            assert attrs["pyresilience.error_message"] == "connection refused"
            assert attrs["pyresilience.detail"] == "retrying in 1.00s"
        finally:
            self._uninstall_mock_otel()

    def test_call_with_success_event_no_error(self) -> None:
        mock_span, _mock_trace = self._install_mock_otel()
        try:
            from pyresilience.contrib.otel import OpenTelemetryListener

            listener = OpenTelemetryListener()
            event = ResilienceEvent(
                event_type=EventType.SUCCESS,
                function_name="my_func",
                attempt=1,
            )
            listener(event)

            mock_span.add_event.assert_called_once()
            call_kwargs = mock_span.add_event.call_args
            attrs = call_kwargs[1]["attributes"]
            assert "pyresilience.error_type" not in attrs
            assert "pyresilience.error_message" not in attrs
            assert "pyresilience.detail" not in attrs
        finally:
            self._uninstall_mock_otel()

    def test_no_op_when_span_not_recording(self) -> None:
        mock_span, _mock_trace = self._install_mock_otel()
        mock_span.is_recording.return_value = False
        try:
            from pyresilience.contrib.otel import OpenTelemetryListener

            listener = OpenTelemetryListener()
            event = ResilienceEvent(
                event_type=EventType.SUCCESS,
                function_name="my_func",
                attempt=1,
            )
            listener(event)

            mock_span.add_event.assert_not_called()
        finally:
            self._uninstall_mock_otel()

    def test_no_op_when_span_is_none(self) -> None:
        _mock_span, _mock_trace = self._install_mock_otel()
        try:
            import pyresilience.contrib.otel as otel_mod
            from pyresilience.contrib.otel import OpenTelemetryListener

            otel_mod.trace.get_current_span = lambda: None  # type: ignore[attr-defined]

            listener = OpenTelemetryListener()
            event = ResilienceEvent(
                event_type=EventType.RETRY,
                function_name="my_func",
                attempt=1,
            )
            # Should not raise
            listener(event)
        finally:
            self._uninstall_mock_otel()
