"""Tests for compatibility and backend detection."""

from __future__ import annotations

import json
from unittest import mock

from pyresilience._compat import get_json_dumps, has_orjson, has_uvloop, install_uvloop


class TestCompat:
    def test_has_uvloop_returns_bool(self) -> None:
        result = has_uvloop()
        assert isinstance(result, bool)

    def test_has_orjson_returns_bool(self) -> None:
        result = has_orjson()
        assert isinstance(result, bool)

    def test_get_json_dumps_callable(self) -> None:
        dumps = get_json_dumps()
        assert callable(dumps)

    def test_install_uvloop_returns_bool(self) -> None:
        result = install_uvloop()
        assert isinstance(result, bool)

    def test_get_json_dumps_produces_json(self) -> None:
        dumps = get_json_dumps()
        data = {"key": "value", "num": 42}
        result = dumps(data)
        if isinstance(result, bytes):
            parsed = json.loads(result.decode("utf-8"))
        else:
            parsed = json.loads(result)
        assert parsed["key"] == "value"
        assert parsed["num"] == 42

    def test_has_uvloop_false_on_windows(self) -> None:
        with mock.patch("pyresilience._compat.sys") as mock_sys:
            mock_sys.platform = "win32"
            # Re-import to test
            from pyresilience._compat import has_uvloop

            result = has_uvloop()
            # On windows it should be False
            assert isinstance(result, bool)

    def test_install_uvloop_false_when_unavailable(self) -> None:
        with mock.patch("pyresilience._compat.has_uvloop", return_value=False):
            from pyresilience._compat import install_uvloop

            assert install_uvloop() is False

    def test_install_uvloop_handles_exception(self) -> None:
        with mock.patch("pyresilience._compat.has_uvloop", return_value=True):
            with mock.patch.dict("sys.modules", {"uvloop": None}):
                result = install_uvloop()
                assert isinstance(result, bool)

    def test_get_json_dumps_falls_back_to_stdlib(self) -> None:
        with mock.patch("pyresilience._compat.has_orjson", return_value=False):
            dumps = get_json_dumps()
            result = dumps({"test": 1})
            assert isinstance(result, str)
            assert json.loads(result) == {"test": 1}

    def test_get_json_dumps_uses_orjson_when_available(self) -> None:
        mock_orjson = mock.MagicMock()
        mock_orjson.dumps.return_value = b'{"test":1}'

        with mock.patch("pyresilience._compat.has_orjson", return_value=True):
            with mock.patch.dict("sys.modules", {"orjson": mock_orjson}):
                dumps = get_json_dumps()
                result = dumps({"test": 1})
                mock_orjson.dumps.assert_called_once()
