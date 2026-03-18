"""Tests for public re-export modules."""

from __future__ import annotations


class TestPresetsModule:
    def test_import_from_presets(self) -> None:
        from pyresilience.presets import db_policy, http_policy, queue_policy, strict_policy

        assert callable(http_policy)
        assert callable(db_policy)
        assert callable(queue_policy)
        assert callable(strict_policy)


class TestLoggingModule:
    def test_import_from_logging(self) -> None:
        from pyresilience.logging import JsonEventLogger, MetricsCollector

        assert callable(JsonEventLogger)
        assert callable(MetricsCollector)
