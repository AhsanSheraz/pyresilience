"""Tests for public re-export modules."""

from __future__ import annotations


class TestPresetsModule:
    def test_import_from_presets(self) -> None:
        from pyresilience.presets import (
            db_policy,
            http_policy,
            llm_policy,
            queue_policy,
            strict_policy,
        )

        assert callable(http_policy)
        assert callable(db_policy)
        assert callable(queue_policy)
        assert callable(llm_policy)
        assert callable(strict_policy)


class TestLoggingModule:
    def test_import_from_logging(self) -> None:
        from pyresilience.logging import JsonEventLogger, MetricsCollector

        assert callable(JsonEventLogger)
        assert callable(MetricsCollector)


class TestLlmPolicyPublicReexport:
    def test_llm_policy_from_root_import(self) -> None:
        from pyresilience import llm_policy as root_llm

        assert callable(root_llm)

    def test_llm_policy_from_presets_import(self) -> None:
        from pyresilience.presets import llm_policy as presets_llm

        assert callable(presets_llm)

    def test_llm_policy_identity_match(self) -> None:
        from pyresilience import llm_policy as root_llm
        from pyresilience.presets import llm_policy as presets_llm

        assert root_llm is presets_llm

    def test_llm_policy_in_all(self) -> None:
        import pyresilience

        assert "llm_policy" in pyresilience.__all__
