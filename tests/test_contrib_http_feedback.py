"""Tests for pyresilience.contrib.http.rate_limit_feedback and the LLM preset limits."""

from __future__ import annotations

import datetime
import email.utils
import time
from typing import Any, Optional

import pytest

from pyresilience import RateLimiterConfig, RateLimitExceededError, llm_policy, resilient
from pyresilience.contrib.http import _parse_reset, rate_limit_feedback


class FakeResponse:
    """Duck-typed HTTP response (requests / httpx shape)."""

    def __init__(self, status_code: int = 200, headers: Optional[Any] = None) -> None:
        self.status_code = status_code
        self.headers = headers if headers is not None else {}


class FakeHttpError(Exception):
    """Exception carrying a response, like requests.HTTPError."""

    def __init__(self, response: FakeResponse) -> None:
        super().__init__("http error")
        self.response = response


class BrokenHeaders:
    def get(self, name: str) -> Any:
        raise RuntimeError("broken mapping")


class TestRateLimitFeedback:
    def test_retry_after_seconds(self) -> None:
        feedback = rate_limit_feedback()(FakeResponse(429, {"retry-after": "7"}))
        assert feedback is not None
        assert feedback.retry_after == 7.0
        assert feedback.remaining is None

    def test_retry_after_http_date(self) -> None:
        when = email.utils.formatdate(time.time() + 30, usegmt=True)
        feedback = rate_limit_feedback()(FakeResponse(503, {"retry-after": when}))
        assert feedback is not None
        assert feedback.retry_after is not None
        assert 20.0 < feedback.retry_after <= 30.5

    def test_retry_after_is_capped_by_max_pause(self) -> None:
        feedback = rate_limit_feedback(max_pause=5.0)(FakeResponse(429, {"retry-after": "120"}))
        assert feedback is not None
        assert feedback.retry_after == 5.0

    def test_retry_after_zero_does_not_pause(self) -> None:
        assert rate_limit_feedback()(FakeResponse(429, {"retry-after": "0"})) is None

    def test_openai_style_headers(self) -> None:
        headers = {
            "x-ratelimit-remaining-requests": "59",
            "x-ratelimit-remaining-tokens": "1500",
            "x-ratelimit-reset-requests": "1s",
            "x-ratelimit-reset-tokens": "6m0s",
        }
        feedback = rate_limit_feedback()(FakeResponse(200, headers))
        assert feedback is not None
        assert feedback.retry_after is None
        assert feedback.remaining == {"calls": 59.0, "tokens": 1500.0}

    def test_exhausted_limit_pauses_until_reset(self) -> None:
        headers = {
            "x-ratelimit-remaining-requests": "0",
            "x-ratelimit-reset-requests": "12s",
        }
        feedback = rate_limit_feedback()(FakeResponse(200, headers))
        assert feedback is not None
        assert feedback.retry_after == 12.0
        assert feedback.remaining == {"calls": 0.0}

    def test_longest_pause_wins(self) -> None:
        headers = {
            "retry-after": "2",
            "x-ratelimit-remaining-tokens": "0",
            "x-ratelimit-reset-tokens": "20s",
        }
        feedback = rate_limit_feedback()(FakeResponse(429, headers))
        assert feedback is not None
        assert feedback.retry_after == 20.0

    def test_exhausted_limit_without_reset_header(self) -> None:
        feedback = rate_limit_feedback()(FakeResponse(200, {"x-ratelimit-remaining": "0"}))
        assert feedback is not None
        assert feedback.retry_after is None
        assert feedback.remaining == {"calls": 0.0}

    def test_anthropic_style_headers(self) -> None:
        reset = (
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=40)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        headers = {
            "anthropic-ratelimit-requests-remaining": "0",
            "anthropic-ratelimit-requests-reset": reset,
            "anthropic-ratelimit-tokens-remaining": "8000",
        }
        feedback = rate_limit_feedback()(FakeResponse(200, headers))
        assert feedback is not None
        assert feedback.retry_after is not None
        assert 30.0 < feedback.retry_after <= 40.5
        assert feedback.remaining == {"calls": 0.0, "tokens": 8000.0}

    def test_ietf_ratelimit_headers(self) -> None:
        headers = {"ratelimit-remaining": "0", "ratelimit-reset": "9"}
        feedback = rate_limit_feedback()(FakeResponse(200, headers))
        assert feedback is not None
        assert feedback.retry_after == 9.0

    def test_plain_dict_headers_are_matched_case_insensitively(self) -> None:
        headers = {"X-RateLimit-Remaining": "3", "Retry-After": "4"}
        feedback = rate_limit_feedback()(FakeResponse(429, headers))
        assert feedback is not None
        assert feedback.retry_after == 4.0
        assert feedback.remaining == {"calls": 3.0}

    def test_headers_on_exception_response(self) -> None:
        error = FakeHttpError(FakeResponse(429, {"retry-after": "3"}))
        feedback = rate_limit_feedback()(error)
        assert feedback is not None
        assert feedback.retry_after == 3.0

    def test_custom_limit_names(self) -> None:
        headers = {"x-ratelimit-remaining-requests": "5", "x-ratelimit-remaining-tokens": "70"}
        feedback = rate_limit_feedback(calls_limit="rpm", tokens_limit="tpm")(
            FakeResponse(200, headers)
        )
        assert feedback is not None
        assert feedback.remaining == {"rpm": 5.0, "tpm": 70.0}

    @pytest.mark.parametrize(
        "outcome",
        [
            "plain string result",
            ValueError("no response attached"),
            FakeResponse(200, {}),
            FakeResponse(200, {"content-type": "application/json"}),
            FakeResponse(200, {"retry-after": "soon", "x-ratelimit-remaining": "many"}),
            FakeResponse(200, BrokenHeaders()),
        ],
    )
    def test_nothing_usable_returns_none(self, outcome: Any) -> None:
        assert rate_limit_feedback()(outcome) is None

    def test_headers_without_items_method(self) -> None:
        class GetOnly:
            def get(self, name: str) -> Any:
                return None

        assert rate_limit_feedback()(FakeResponse(200, GetOnly())) is None

    def test_max_pause_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_pause must be > 0"):
            rate_limit_feedback(max_pause=0)


class TestParseReset:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("30", 30.0),
            (" 2.5 ", 2.5),
            ("-4", 0.0),
            ("20ms", 0.02),
            ("1s", 1.0),
            ("6m0s", 360.0),
            ("1h2m3.5s", 3723.5),
        ],
    )
    def test_relative_values(self, raw: str, expected: float) -> None:
        assert _parse_reset(raw) == pytest.approx(expected)

    def test_epoch_seconds(self) -> None:
        delay = _parse_reset(str(time.time() + 50))
        assert delay is not None
        assert 40.0 < delay <= 50.5

    def test_epoch_milliseconds(self) -> None:
        delay = _parse_reset(str((time.time() + 50) * 1000))
        assert delay is not None
        assert 40.0 < delay <= 50.5

    def test_naive_timestamp_is_read_as_utc(self) -> None:
        moment = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=60)
        delay = _parse_reset(moment.strftime("%Y-%m-%dT%H:%M:%S"))
        assert delay is not None
        assert 50.0 < delay <= 60.5

    def test_http_date(self) -> None:
        delay = _parse_reset(email.utils.formatdate(time.time() + 45, usegmt=True))
        assert delay is not None
        assert 35.0 < delay <= 45.5

    def test_past_timestamp_is_zero(self) -> None:
        assert _parse_reset("2020-01-01T00:00:00Z") == 0.0

    @pytest.mark.parametrize("raw", [None, "", "soon", "5 minutes", "12x"])
    def test_unparseable_values(self, raw: Optional[str]) -> None:
        assert _parse_reset(raw) is None


class TestLlmPolicyLimits:
    def test_defaults_are_unchanged(self) -> None:
        limiter = llm_policy()["rate_limiter"]
        assert isinstance(limiter, RateLimiterConfig)
        assert limiter.max_calls == 60
        assert limiter.max_wait == 0.0
        assert limiter.limits == ()
        assert limiter.feedback is None
        assert limiter.charge_retries is False

    def test_tokens_per_minute_adds_a_token_limit(self) -> None:
        limiter = llm_policy(tokens_per_minute=90_000, token_cost=lambda prompt: len(prompt))[
            "rate_limiter"
        ]
        assert len(limiter.limits) == 1
        tokens = limiter.limits[0]
        assert tokens.name == "tokens"
        assert tokens.max_units == 90_000
        assert tokens.period == 60.0
        assert limiter.charge_retries is True

    def test_tokens_per_minute_needs_a_cost_source(self) -> None:
        with pytest.raises(ValueError, match="tokens_per_minute requires token_cost"):
            llm_policy(tokens_per_minute=1000)

    def test_token_usage_alone_is_enough(self) -> None:
        limiter = llm_policy(tokens_per_minute=1000, token_usage=lambda r: r["usage"])[
            "rate_limiter"
        ]
        assert limiter.limits[0].cost is None
        assert limiter.limits[0].actual_cost is not None

    def test_adaptive_rate_limit_sets_feedback(self) -> None:
        limiter = llm_policy(adaptive_rate_limit=True, rate_limit_max_wait=2.5)["rate_limiter"]
        assert limiter.feedback is not None
        assert limiter.max_wait == 2.5

    def test_token_budget_end_to_end_sync(self) -> None:
        policy = llm_policy(
            tokens_per_minute=1000,
            token_cost=lambda prompt: 600,
            token_usage=lambda response: response["usage"],
        )

        @resilient(**policy)
        def complete(prompt: str) -> dict[str, Any]:
            return {"text": "ok", "usage": 500}

        complete("first")  # reserves 600, really used 500
        with pytest.raises(RateLimitExceededError, match="tokens"):
            complete("second")  # 500 left, 600 needed

    async def test_adaptive_limit_end_to_end_async(self) -> None:
        calls = 0

        @resilient(**llm_policy(adaptive_rate_limit=True, max_attempts=1))
        async def complete(prompt: str) -> FakeResponse:
            nonlocal calls
            calls += 1
            return FakeResponse(429, {"retry-after": "30"})

        response = await complete("first")
        assert response.status_code == 429
        with pytest.raises(RateLimitExceededError, match="server feedback"):
            await complete("second")
        # The second call never reached the server
        assert calls == 1
