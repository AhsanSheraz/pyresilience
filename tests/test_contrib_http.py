"""Tests for HTTP resilience helpers (contrib.http module)."""

from __future__ import annotations

import email.utils
import time
from pathlib import Path
from typing import ClassVar

import pytest


class TestRetryOnStatus:
    """Tests for retry_on_status predicate factory."""

    def test_matches_requests_httpx_shape_status_code(self) -> None:
        """Predicate returns True for response with matching status_code."""
        from pyresilience.contrib.http import retry_on_status

        predicate = retry_on_status(429)

        class Response:
            status_code: ClassVar = 429

        assert predicate(Response()) is True

    def test_matches_aiohttp_shape_status(self) -> None:
        """Predicate returns True for aiohttp-style response with matching status."""
        from pyresilience.contrib.http import retry_on_status

        predicate = retry_on_status(503)

        class Response:
            status: ClassVar = 503

        assert predicate(Response()) is True

    def test_returns_false_for_non_matching_status(self) -> None:
        """Predicate returns False when status does not match any code."""
        from pyresilience.contrib.http import retry_on_status

        predicate = retry_on_status(429, 500, 503)

        class Response:
            status_code: ClassVar = 200

        assert predicate(Response()) is False

    def test_returns_false_for_string_status_code(self) -> None:
        """Predicate returns False when status_code is a string."""
        from pyresilience.contrib.http import retry_on_status

        predicate = retry_on_status(429)

        class Response:
            status_code: ClassVar = "429"

        assert predicate(Response()) is False

    def test_returns_false_for_bool_status_code(self) -> None:
        """Predicate returns False when status_code is a bool (bool is subclass of int)."""
        from pyresilience.contrib.http import retry_on_status

        predicate = retry_on_status(1)

        class Response:
            status_code: ClassVar = True  # bool

        assert predicate(Response()) is False

    def test_returns_false_for_missing_attributes(self) -> None:
        """Predicate returns False for object with neither status_code nor status."""
        from pyresilience.contrib.http import retry_on_status

        predicate = retry_on_status(429)

        class EmptyResponse:
            pass

        assert predicate(EmptyResponse()) is False

    def test_returns_false_for_none(self) -> None:
        """Predicate returns False for None."""
        from pyresilience.contrib.http import retry_on_status

        predicate = retry_on_status(429)
        assert predicate(None) is False

    def test_returns_false_for_plain_exception(self) -> None:
        """Predicate returns False for Exception instances."""
        from pyresilience.contrib.http import retry_on_status

        predicate = retry_on_status(429)
        exc = Exception("error")
        assert predicate(exc) is False

    def test_no_codes_raises_value_error(self) -> None:
        """Factory raises ValueError when called with no arguments."""
        from pyresilience.contrib.http import retry_on_status

        with pytest.raises(ValueError, match="retry_on_status requires at least one status code"):
            retry_on_status()

    def test_non_int_code_raises_type_error(self) -> None:
        """Factory raises TypeError when a code is not an int."""
        from pyresilience.contrib.http import retry_on_status

        with pytest.raises(TypeError):
            retry_on_status("429")  # type: ignore[arg-type]

    def test_bool_code_raises_type_error(self) -> None:
        """Factory raises TypeError when a code is a bool."""
        from pyresilience.contrib.http import retry_on_status

        with pytest.raises(TypeError):
            retry_on_status(True)  # type: ignore[arg-type]

    def test_multiple_codes(self) -> None:
        """Predicate works with multiple codes."""
        from pyresilience.contrib.http import retry_on_status

        predicate = retry_on_status(429, 500, 502, 503, 504)

        class Response:
            status_code: ClassVar = 502

        assert predicate(Response()) is True

        class Response2:
            status_code: ClassVar = 200

        assert predicate(Response2()) is False


class TestRetryAfterDelay:
    """Tests for retry_after_delay delay_func factory."""

    def test_parses_delta_seconds_form(self) -> None:
        """Delay func parses Retry-After as delta-seconds."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        class Response:
            def __init__(self) -> None:
                self.headers = {"Retry-After": "5"}

        result = delay_func(1, Response())
        assert result == 5.0

    def test_parses_delta_seconds_float(self) -> None:
        """Delay func parses float delta-seconds."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        class Response:
            def __init__(self) -> None:
                self.headers = {"Retry-After": "2.5"}

        result = delay_func(1, Response())
        assert result == 2.5

    def test_case_insensitive_header_lookup(self) -> None:
        """Delay func finds Retry-After header case-insensitively."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        class ResponseLower:
            def __init__(self) -> None:
                self.headers = {"retry-after": "3"}

        assert delay_func(1, ResponseLower()) == 3.0

        class ResponseUpper:
            def __init__(self) -> None:
                self.headers = {"RETRY-AFTER": "4"}

        assert delay_func(1, ResponseUpper()) == 4.0

    def test_parses_http_date_form(self) -> None:
        """Delay func parses Retry-After as HTTP-date (RFC 2822)."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        # Create a date 10 seconds in the future
        future_time = time.time() + 10
        http_date = email.utils.formatdate(timeval=future_time, usegmt=True)

        class Response:
            def __init__(self, date: str) -> None:
                self.headers = {"Retry-After": date}

        result = delay_func(1, Response(http_date))
        # Allow 2 second tolerance for execution time
        assert result == pytest.approx(10.0, abs=2.0)

    def test_http_date_in_past_clamped_to_zero(self) -> None:
        """Delay func clamps negative (past) dates to 0.0."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        # Create a date 5 seconds in the past
        past_time = time.time() - 5
        http_date = email.utils.formatdate(timeval=past_time, usegmt=True)

        class Response:
            def __init__(self, date: str) -> None:
                self.headers = {"Retry-After": date}

        result = delay_func(1, Response(http_date))
        assert result == 0.0

    def test_negative_delta_clamped_to_zero(self) -> None:
        """Delay func clamps negative delta-seconds to 0.0."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        class Response:
            def __init__(self) -> None:
                self.headers = {"Retry-After": "-5"}

        result = delay_func(1, Response())
        assert result == 0.0

    def test_huge_delta_clamped_to_max_wait(self) -> None:
        """Delay func clamps large deltas to max_wait."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=30.0)

        class Response:
            def __init__(self) -> None:
                self.headers = {"Retry-After": "999999"}

        result = delay_func(1, Response())
        assert result == 30.0

    def test_exception_trigger_with_response_attribute(self) -> None:
        """Delay func extracts headers from exception.response.headers."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        class FakeResponse:
            def __init__(self) -> None:
                self.headers = {"Retry-After": "3"}

        class FakeApiError(Exception):
            pass

        exc = FakeApiError("api error")
        exc.response = FakeResponse()  # type: ignore[attr-defined]

        result = delay_func(1, exc)
        assert result == 3.0

    def test_missing_header_returns_none(self) -> None:
        """Delay func returns None when Retry-After header is missing."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        class Response:
            def __init__(self) -> None:
                self.headers = {"Content-Type": "application/json"}

        result = delay_func(1, Response())
        assert result is None

    def test_malformed_header_returns_none(self) -> None:
        """Delay func returns None when header value cannot be parsed."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        class Response:
            def __init__(self) -> None:
                self.headers = {"Retry-After": "banana"}

        result = delay_func(1, Response())
        assert result is None

    def test_plain_exception_returns_none(self) -> None:
        """Delay func returns None for exception with no response attribute."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        exc = ValueError("error")
        result = delay_func(1, exc)
        assert result is None

    def test_max_wait_zero_raises_value_error(self) -> None:
        """Factory raises ValueError when max_wait <= 0."""
        from pyresilience.contrib.http import retry_after_delay

        with pytest.raises(ValueError, match="max_wait must be > 0"):
            retry_after_delay(max_wait=0)

    def test_max_wait_negative_raises_value_error(self) -> None:
        """Factory raises ValueError when max_wait is negative."""
        from pyresilience.contrib.http import retry_after_delay

        with pytest.raises(ValueError, match="max_wait must be > 0"):
            retry_after_delay(max_wait=-1.0)

    def test_result_trigger_type(self) -> None:
        """Delay func receives the result object for retry_on_result triggers."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        # Simulate a response returned from retry_on_result
        class Response:
            def __init__(self) -> None:
                self.headers = {"Retry-After": "7"}

        result = delay_func(1, Response())
        assert result == 7.0

    def test_trigger_with_neither_headers_nor_response(self) -> None:
        """Delay func returns None when trigger has neither .headers nor .response."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        class NotAResponse:
            data = "something"

        result = delay_func(1, NotAResponse())
        assert result is None

    def test_exception_during_getattr_returns_none(self) -> None:
        """Delay func returns None when getattr raises an exception."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        class BadObject:
            @property
            def headers(self) -> None:
                raise RuntimeError("broken property")

        result = delay_func(1, BadObject())
        assert result is None

    def test_exception_during_header_get_returns_none(self) -> None:
        """Delay func returns None when headers.get() raises an exception."""
        from pyresilience.contrib.http import retry_after_delay

        delay_func = retry_after_delay(max_wait=60.0)

        class BadHeaders:
            def get(self, key: str) -> None:
                raise RuntimeError("broken headers.get")

        class Response:
            def __init__(self) -> None:
                self.headers = BadHeaders()

        result = delay_func(1, Response())
        assert result is None


class TestContribHttpModuleHygiene:
    """Tests for module structure and import hygiene."""

    def test_no_third_party_http_imports(self) -> None:
        """Verify contrib/http.py does not import requests/httpx/aiohttp."""
        from pyresilience.contrib import http as http_module

        src_text = Path(http_module.__file__).read_text(encoding="utf-8")

        assert "import requests" not in src_text
        assert "from requests" not in src_text
        assert "import httpx" not in src_text
        assert "from httpx" not in src_text
        assert "import aiohttp" not in src_text
        assert "from aiohttp" not in src_text

    def test_module_exports_correct_all(self) -> None:
        """Verify __all__ contains exactly retry_on_status and retry_after_delay."""
        from pyresilience.contrib import http as http_module

        assert http_module.__all__ == ["retry_after_delay", "retry_on_status"]
