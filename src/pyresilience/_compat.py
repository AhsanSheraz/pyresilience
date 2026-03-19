"""Runtime compatibility and performance backend detection.

Auto-detects and configures high-performance backends:
- uvloop (C-based event loop) on Linux/macOS
- orjson (Rust-based JSON) for fast serialization
"""

from __future__ import annotations

import importlib.util
import sys
from typing import Any


def has_uvloop() -> bool:
    """Check if uvloop is available."""
    if sys.platform == "win32":
        return False
    return importlib.util.find_spec("uvloop") is not None


def has_orjson() -> bool:
    """Check if orjson is available."""
    return importlib.util.find_spec("orjson") is not None


def install_uvloop() -> bool:
    """Install uvloop as the default event loop policy if available.

    Returns True if uvloop was installed, False otherwise.
    Uses asyncio.set_event_loop_policy() for Python 3.16+ compatibility.
    """
    if not has_uvloop():
        return False
    try:
        import asyncio

        import uvloop

        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        return True
    except Exception:
        return False


def get_json_dumps() -> Any:
    """Get the best available JSON dumps function.

    Returns orjson.dumps if available, falls back to json.dumps.
    """
    if has_orjson():
        import orjson

        return orjson.dumps
    import json

    return json.dumps
