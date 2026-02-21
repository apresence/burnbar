import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

logger = logging.getLogger("burnbar.api_client")


class ApiError(Exception):
    """Raised when the API call fails or returns unexpected data."""


@dataclass
class UsageInfo:
    tokens_remaining: int
    tokens_limit: int
    requests_remaining: int
    requests_limit: int
    reset_time: str = ""

    @property
    def percentage(self) -> float:
        if self.tokens_limit <= 0:
            return 100.0
        return max(0.0, min(100.0,
                            (self.tokens_remaining / self.tokens_limit) * 100.0))

    @property
    def summary(self) -> str:
        return (f"{self.percentage:.0f}% "
                f"({self.tokens_remaining:,} / {self.tokens_limit:,} tokens)")

    @property
    def detail_line(self) -> str:
        return (f"{self.tokens_remaining:,} / "
                f"{self.tokens_limit:,} tokens")

    @property
    def reset_display(self) -> str:
        if not self.reset_time:
            return ""
        try:
            dt = datetime.fromisoformat(self.reset_time.replace("Z", "+00:00"))
            local_dt = dt.astimezone()
            return local_dt.strftime("%I:%M %p").lstrip("0")
        except (ValueError, OSError):
            return self.reset_time

    def tooltip(self) -> str:
        """Format tooltip for API key mode (single line)."""
        return (f"{self.percentage:.0f}% remaining\n"
                f"{self.tokens_remaining:,} / {self.tokens_limit:,} tokens\n"
                f"Resets: {self.reset_display}" if self.reset_display else
                f"{self.percentage:.0f}% remaining\n"
                f"{self.tokens_remaining:,} / {self.tokens_limit:,} tokens")


@dataclass
class UnifiedUsageInfo:
    """Usage info from Max plan unified rate-limit headers."""
    utilization_5h: float        # 0.0-1.0 from header
    utilization_7d: float        # 0.0-1.0 from header
    utilization_7d_sonnet: float  # 0.0-1.0 (Sonnet-specific 7d window)
    reset_5h: int                # epoch seconds
    reset_7d: int                # epoch seconds
    reset_7d_sonnet: int         # epoch seconds

    @property
    def percentage(self) -> float:
        """Remaining capacity as 0-100 percentage."""
        used = max(self.utilization_5h, self.utilization_7d,
                   self.utilization_7d_sonnet)
        return max(0.0, min(100.0, (1.0 - used) * 100.0))

    @property
    def summary(self) -> str:
        return f"{self.percentage:.0f}% remaining"

    @property
    def detail_line(self) -> str:
        pct_5h = self.utilization_5h * 100
        pct_7d = self.utilization_7d * 100
        pct_son = self.utilization_7d_sonnet * 100
        return f"5h: {pct_5h:.0f}% | 7d: {pct_7d:.0f}% | Sonnet: {pct_son:.0f}%"

    @property
    def utilizations(self) -> tuple[float, float, float]:
        """Utilization tuple for the 3-bar icon (5h, 7d all, 7d Sonnet)."""
        return (self.utilization_5h, self.utilization_7d, self.utilization_7d_sonnet)

    @property
    def reset_display(self) -> str:
        """Human-readable reset time for the most-utilized window."""
        windows = [
            (self.utilization_5h, self.reset_5h, "5h"),
            (self.utilization_7d, self.reset_7d, "7d"),
            (self.utilization_7d_sonnet, self.reset_7d_sonnet, "Sonnet"),
        ]
        best = max(windows, key=lambda w: w[0])
        epoch, label = best[1], best[2]
        if epoch <= 0:
            return ""
        try:
            dt = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone()
            time_str = dt.strftime("%I:%M %p").lstrip("0")
            return f"{time_str} ({label})"
        except (ValueError, OSError, OverflowError):
            return ""

    @property
    def has_reset(self) -> bool:
        return self.reset_5h > 0 or self.reset_7d > 0 or self.reset_7d_sonnet > 0

    def tooltip(self) -> str:
        """Format a multi-line tooltip showing all three usage windows.

        Example:
            Session 62% 37 min
            Week 19% Mon 7:00 PM
            Sonnet 1% Mon 7:00 PM
        """
        lines = []

        # Session (5h)
        pct_5h = self.utilization_5h * 100
        reset_str_5h = self._format_reset_time(self.reset_5h)
        lines.append(f"Session {pct_5h:.0f}% {reset_str_5h}")

        # Weekly (7d all)
        pct_7d = self.utilization_7d * 100
        reset_str_7d = self._format_reset_time(self.reset_7d)
        lines.append(f"Week {pct_7d:.0f}% {reset_str_7d}")

        # Sonnet (7d sonnet)
        pct_son = self.utilization_7d_sonnet * 100
        reset_str_son = self._format_reset_time(self.reset_7d_sonnet)
        lines.append(f"Sonnet {pct_son:.0f}% {reset_str_son}")

        return "\n".join(lines)

    def _format_reset_time(self, epoch: int) -> str:
        """Format reset time as 'X min', 'HH:MM AM/PM', or 'Day HH:MM AM/PM'."""
        if epoch <= 0:
            return "unknown"

        try:
            now = datetime.fromtimestamp(0, tz=timezone.utc).astimezone()
            now = datetime.now(tz=timezone.utc).astimezone()
            reset_dt = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone()

            # Calculate time remaining
            delta = reset_dt - now
            total_secs = int(delta.total_seconds())

            if total_secs <= 0:
                return "now"

            # Less than 1 hour: show minutes
            if total_secs < 3600:
                mins = max(1, total_secs // 60)
                return f"{mins} min"

            # Less than 24 hours: show time only
            if total_secs < 86400:
                return reset_dt.strftime("%I:%M %p").lstrip("0")

            # 24+ hours: show day + time
            return reset_dt.strftime("%a %I:%M %p").lstrip("0")

        except (ValueError, OSError, OverflowError):
            return "unknown"


class AnthropicClient:
    API_BASE = "https://api.anthropic.com/v1"

    def __init__(self, api_key: str = "", endpoint_mode: str = "both",
                 auth_mode: str = "api_key", access_token: str = ""):
        self.api_key = api_key
        self.endpoint_mode = endpoint_mode
        self.auth_mode = auth_mode
        self.access_token = access_token

    # ------------------------------------------------------------------ #
    #  Public
    # ------------------------------------------------------------------ #

    def check_usage(self) -> UsageInfo | UnifiedUsageInfo:
        """Query the API and return current rate-limit usage info.

        For OAuth (Max plan): always uses messages endpoint, returns UnifiedUsageInfo.
        For API key: uses endpoint_mode strategy, returns UsageInfo.
        """
        if self.auth_mode == "oauth":
            return self._check_usage_oauth()
        return self._check_usage_api_key()

    # ------------------------------------------------------------------ #
    #  API key mode (existing behavior)
    # ------------------------------------------------------------------ #

    def _check_usage_api_key(self) -> UsageInfo:
        if not self.api_key:
            raise ApiError("API key not configured")

        last_error = None

        if self.endpoint_mode in ("both", "count_tokens"):
            try:
                logger.debug("Trying count_tokens endpoint")
                resp = self._call_count_tokens()
                if self._has_ratelimit_headers(resp):
                    usage = self._parse_headers(resp)
                    logger.debug("Got usage from count_tokens: %s", usage.summary)
                    return usage
                logger.debug("count_tokens returned no rate-limit headers")
            except ApiError as exc:
                last_error = exc
                if self.endpoint_mode == "count_tokens":
                    raise
                logger.warning("count_tokens failed (%s), will try messages", exc)

        if self.endpoint_mode in ("both", "messages"):
            try:
                logger.debug("Trying messages endpoint")
                resp = self._call_messages_minimal()
                if self._has_ratelimit_headers(resp):
                    usage = self._parse_headers(resp)
                    logger.debug("Got usage from messages: %s", usage.summary)
                    return usage
                logger.debug("messages returned no rate-limit headers")
            except ApiError as exc:
                last_error = exc
                raise

        raise last_error or ApiError("API did not return rate-limit headers")

    # ------------------------------------------------------------------ #
    #  OAuth mode (Max plan)
    # ------------------------------------------------------------------ #

    def _check_usage_oauth(self) -> UnifiedUsageInfo:
        if not self.access_token:
            raise ApiError("OAuth token not configured")

        logger.debug("Trying messages endpoint (OAuth)")
        resp = self._call_messages_minimal()

        if self._has_unified_headers(resp):
            usage = self._parse_unified_headers(resp)
            logger.debug("Got unified usage: %s", usage.summary)
            return usage

        # Fallback: if we got standard headers, report via UnifiedUsageInfo
        if self._has_ratelimit_headers(resp):
            std = self._parse_headers(resp)
            logger.warning("OAuth returned standard headers, not unified; "
                           "converting to UnifiedUsageInfo")
            utilization = 1.0 - (std.percentage / 100.0)
            return UnifiedUsageInfo(
                utilization_5h=utilization,
                utilization_7d=0.0,
                utilization_7d_sonnet=0.0,
                reset_5h=0,
                reset_7d=0,
                reset_7d_sonnet=0,
            )

        raise ApiError("API did not return usage headers (OAuth)")

    # ------------------------------------------------------------------ #
    #  Internals
    # ------------------------------------------------------------------ #

    def _headers(self):
        if self.auth_mode == "oauth":
            return {
                "Authorization": f"Bearer {self.access_token}",
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "oauth-2025-04-20",
                "content-type": "application/json",
            }
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _call_count_tokens(self) -> requests.Response:
        try:
            resp = requests.post(
                f"{self.API_BASE}/messages/count_tokens",
                headers=self._headers(),
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "x"}],
                },
                timeout=15,
            )
        except requests.ConnectionError:
            raise ApiError("Network error -- check your connection")
        except requests.Timeout:
            raise ApiError("Request timed out")

        logger.debug("count_tokens response: %d", resp.status_code)
        self._check_status(resp)
        return resp

    def _call_messages_minimal(self) -> requests.Response:
        """One-token completion to read rate-limit headers.

        OAuth mode uses Sonnet so the response includes the 7d_sonnet
        utilization headers (only returned for Sonnet-class models).
        API key mode uses Haiku to minimise cost.
        """
        model = ("claude-sonnet-4-6" if self.auth_mode == "oauth"
                 else "claude-haiku-4-5-20251001")
        try:
            resp = requests.post(
                f"{self.API_BASE}/messages",
                headers=self._headers(),
                json={
                    "model": model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "."}],
                },
                timeout=15,
            )
        except requests.ConnectionError:
            raise ApiError("Network error -- check your connection")
        except requests.Timeout:
            raise ApiError("Request timed out")

        logger.debug("messages response: %d", resp.status_code)
        self._check_status(resp)
        return resp

    def _check_status(self, resp: requests.Response):
        if resp.status_code == 401:
            raise ApiError("Invalid API key" if self.auth_mode != "oauth"
                           else "OAuth token invalid or expired")
        if resp.status_code == 403:
            raise ApiError("API key lacks permission" if self.auth_mode != "oauth"
                           else "OAuth token lacks permission")
        if resp.status_code == 400:
            msg = ""
            try:
                msg = resp.json().get("error", {}).get("message", "")
            except Exception:
                pass
            if "credit balance" in msg.lower() or "billing" in msg.lower():
                raise ApiError("No API credits -- check Plans & Billing")
            logger.error("HTTP 400: %s", msg or resp.text[:200])
            raise ApiError(f"Bad request: {msg}" if msg else "Bad request")
        if resp.status_code == 429:
            return  # caller will read headers
        if resp.status_code >= 500:
            raise ApiError(f"Anthropic server error ({resp.status_code})")
        if resp.status_code not in (200, 429):
            body = ""
            try:
                body = resp.json().get("error", {}).get("message", "")
            except Exception:
                pass
            logger.error("HTTP %d: %s", resp.status_code, body or resp.text[:200])
            raise ApiError(f"Unexpected status {resp.status_code}: {body}" if body
                           else f"Unexpected status {resp.status_code}")

    # ------------------------------------------------------------------ #
    #  Header parsing
    # ------------------------------------------------------------------ #

    @staticmethod
    def _has_ratelimit_headers(resp: requests.Response) -> bool:
        return "anthropic-ratelimit-tokens-limit" in resp.headers

    @staticmethod
    def _has_unified_headers(resp: requests.Response) -> bool:
        return "anthropic-ratelimit-unified-5h-utilization" in resp.headers

    def _parse_headers(self, resp: requests.Response) -> UsageInfo:
        h = resp.headers
        exhausted = resp.status_code == 429

        tokens_limit = _hint(h, "anthropic-ratelimit-tokens-limit")
        tokens_remaining = (
            0 if exhausted
            else _hint(h, "anthropic-ratelimit-tokens-remaining")
        )
        requests_limit = _hint(h, "anthropic-ratelimit-requests-limit")
        requests_remaining = (
            0 if exhausted
            else _hint(h, "anthropic-ratelimit-requests-remaining")
        )
        reset_time = h.get("anthropic-ratelimit-tokens-reset", "")

        if tokens_limit == 0:
            raise ApiError("Rate-limit headers present but token limit is 0")

        return UsageInfo(
            tokens_remaining=tokens_remaining,
            tokens_limit=tokens_limit,
            requests_remaining=requests_remaining,
            requests_limit=requests_limit,
            reset_time=reset_time,
        )

    def _parse_unified_headers(self, resp: requests.Response) -> UnifiedUsageInfo:
        h = resp.headers
        exhausted = resp.status_code == 429

        utilization_5h = _hfloat(h, "anthropic-ratelimit-unified-5h-utilization")
        utilization_7d = _hfloat(h, "anthropic-ratelimit-unified-7d-utilization")
        utilization_7d_sonnet = _hfloat(h, "anthropic-ratelimit-unified-7d_sonnet-utilization")
        reset_5h = _hint(h, "anthropic-ratelimit-unified-5h-reset")
        reset_7d = _hint(h, "anthropic-ratelimit-unified-7d-reset")
        reset_7d_sonnet = _hint(h, "anthropic-ratelimit-unified-7d_sonnet-reset")

        if exhausted:
            utilization_5h = max(utilization_5h, 1.0)

        return UnifiedUsageInfo(
            utilization_5h=utilization_5h,
            utilization_7d=utilization_7d,
            utilization_7d_sonnet=utilization_7d_sonnet,
            reset_5h=reset_5h,
            reset_7d=reset_7d,
            reset_7d_sonnet=reset_7d_sonnet,
        )


def _hint(headers, key: str) -> int:
    try:
        return int(headers.get(key, "0"))
    except (ValueError, TypeError):
        return 0


def _hfloat(headers, key: str) -> float:
    try:
        return float(headers.get(key, "0"))
    except (ValueError, TypeError):
        return 0.0
