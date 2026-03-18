"""Dependency-specific resilience presets — public re-export."""

from pyresilience._presets import db_policy, http_policy, queue_policy, strict_policy

__all__ = ["db_policy", "http_policy", "queue_policy", "strict_policy"]
