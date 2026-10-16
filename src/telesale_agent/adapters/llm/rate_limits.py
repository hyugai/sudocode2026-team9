"""Share provider cooldowns between perception, agent calls, and memory writes."""

import math
import re
import time


def is_rate_limit_error(error: BaseException) -> bool:
    return (getattr(error, "status_code", None) or getattr(error, "code", None)) == 429


def retry_after_seconds(error: BaseException) -> int:
    headers = getattr(getattr(error, "response", None), "headers", {})
    value = headers.get("retry-after") if headers else None
    try:
        seconds = float(value)
        if math.isfinite(seconds) and seconds > 0:
            return math.ceil(seconds)
    except (TypeError, ValueError):
        pass
    # Groq includes fractional seconds in the error message when no header is sent.
    match = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*(ms|s|m|h)\b", str(error), re.IGNORECASE)
    if match:
        seconds = float(match[1]) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[match[2].lower()]
        if math.isfinite(seconds) and seconds > 0:
            return max(1, math.ceil(seconds))
    return 30


class ProviderCooldown:
    def __init__(self) -> None:
        self.retry_at = 0.0

    def remaining(self) -> int:
        return max(0, math.ceil(self.retry_at - time.monotonic()))

    def record(self, error: BaseException) -> int:
        self.retry_at = max(self.retry_at, time.monotonic() + retry_after_seconds(error))
        return self.remaining()


provider_cooldown = ProviderCooldown()
