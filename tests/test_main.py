"""Tests for __main__ module."""

from __future__ import annotations

from pyresilience.__main__ import main


def test_main_output(capsys: object) -> None:
    import io
    import sys

    captured = io.StringIO()
    sys.stdout = captured
    try:
        main()
    finally:
        sys.stdout = sys.__stdout__

    output = captured.getvalue()
    import pyresilience

    assert "pyresilience" in output
    assert f"v{pyresilience.__version__}" in output


class TestMainModule:
    def test_main_as_script(self) -> None:
        """Test running as python -m pyresilience."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "pyresilience"],
            capture_output=True,
            text=True,
        )
        assert "pyresilience" in result.stdout
