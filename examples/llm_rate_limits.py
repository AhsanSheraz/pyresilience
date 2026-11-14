"""LLM-grade rate limiting — requests and tokens per minute, settled against real usage.

The fake provider below answers like an LLM API: it reports token usage and, once it
has seen enough traffic, replies 429 with a Retry-After header. Runs without network.
"""

import time
from typing import Optional

from pyresilience import (
    RateLimit,
    RateLimiterConfig,
    RateLimitExceededError,
    resilient,
)
from pyresilience.contrib.http import rate_limit_feedback


class Usage:
    def __init__(self, total_tokens: int) -> None:
        self.total_tokens = total_tokens


class Response:
    """Shaped like an HTTP client response: status code, headers, usage."""

    def __init__(self, status_code: int, headers: dict, usage: Optional[Usage] = None) -> None:
        self.status_code = status_code
        self.headers = headers
        self.usage = usage


class FakeProvider:
    """Throttles the fourth request with a 429 and a short Retry-After."""

    def __init__(self) -> None:
        self.requests = 0

    def complete(self, prompt: str) -> Response:
        self.requests += 1
        if self.requests == 4:
            return Response(429, {"retry-after": "1"})
        used = len(prompt) // 4 + 20
        return Response(200, {"x-ratelimit-remaining-requests": "50"}, Usage(used))


provider = FakeProvider()


def estimate_tokens(prompt: str) -> int:
    """Rough estimate reserved before the call: prompt tokens plus the completion budget."""
    return len(prompt) // 4 + 100


@resilient(
    rate_limiter=RateLimiterConfig(
        max_calls=60,  # requests per minute
        period=60.0,
        limits=[
            RateLimit(
                max_units=600,  # tokens per minute (tiny, to show the limit at work)
                period=60.0,
                name="tokens",
                cost=estimate_tokens,
                actual_cost=lambda response: response.usage.total_tokens if response.usage else 0,
            )
        ],
        feedback=rate_limit_feedback(),  # follow Retry-After and x-ratelimit-* headers
    ),
)
def complete(prompt: str) -> Response:
    return provider.complete(prompt)


if __name__ == "__main__":
    limiter = complete._executor._weighted_limiter  # type: ignore[attr-defined]

    print("=== Token accounting ===")
    for index in range(3):
        response = complete("Summarise the incident report in two sentences. " * 2)
        levels = limiter.levels()
        print(
            f"call {index + 1}: status={response.status_code} "
            f"used={response.usage.total_tokens} tokens, "
            f"{levels['tokens']:.0f} tokens and {levels['calls']:.0f} calls left"
        )

    print("\n=== Server says slow down ===")
    response = complete("Another question")
    print(f"call 4: status={response.status_code}, Retry-After={response.headers['retry-after']}s")
    try:
        complete("This one is not even sent")
    except RateLimitExceededError as exc:
        print(f"call 5: held back locally -> {exc}")

    time.sleep(1.1)
    response = complete("After the pause")
    print(f"call 6: status={response.status_code} (pause is over)")
    print(f"\nRequests that reached the provider: {provider.requests}")
