import json
import os
from pathlib import Path

if os.name == "nt":
    CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "BurnBar"
else:
    CONFIG_DIR = Path.home() / ".config" / "burnbar"

CONFIG_FILE = CONFIG_DIR / "config.json"

AUTH_MODES = ("oauth", "api_key")
ENDPOINT_MODES = ("both", "count_tokens", "messages")

DEFAULTS = {
    "auth_mode": "oauth",
    "api_key": "",
    "poll_interval_seconds": 60,
    "yellow_threshold_pct": 25,
    "red_threshold_pct": 5,
    "critical_threshold_pct": 3,
    "endpoint_mode": "both",  # "both", "count_tokens", or "messages"
    "oauth_access_token": "",
    "oauth_refresh_token": "",
    "oauth_expires_at": 0,
    "overlay_x": -1,
    "overlay_y": -1,
}


class Config:
    def __init__(self):
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r") as f:
                    self._data.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(self._data, f, indent=2)

    # ---- Auth mode ----

    @property
    def auth_mode(self):
        val = self._data.get("auth_mode", "oauth")
        return val if val in AUTH_MODES else "oauth"

    @auth_mode.setter
    def auth_mode(self, value):
        if value not in AUTH_MODES:
            value = "oauth"
        self._data["auth_mode"] = value

    # ---- API key ----

    @property
    def api_key(self):
        """Config file value takes precedence; falls back to ANTHROPIC_API_KEY env var."""
        key = self._data.get("api_key", "")
        if not key:
            key = os.environ.get("ANTHROPIC_API_KEY", "")
        return key

    @api_key.setter
    def api_key(self, value):
        self._data["api_key"] = value

    # ---- OAuth tokens ----

    @property
    def oauth_access_token(self):
        return self._data.get("oauth_access_token", "")

    @oauth_access_token.setter
    def oauth_access_token(self, value):
        self._data["oauth_access_token"] = value

    @property
    def oauth_refresh_token(self):
        return self._data.get("oauth_refresh_token", "")

    @oauth_refresh_token.setter
    def oauth_refresh_token(self, value):
        self._data["oauth_refresh_token"] = value

    @property
    def oauth_expires_at(self):
        return self._data.get("oauth_expires_at", 0)

    @oauth_expires_at.setter
    def oauth_expires_at(self, value):
        self._data["oauth_expires_at"] = int(value)

    # ---- Poll interval ----

    @property
    def poll_interval_seconds(self):
        return self._data.get("poll_interval_seconds", 60)

    @poll_interval_seconds.setter
    def poll_interval_seconds(self, value):
        self._data["poll_interval_seconds"] = max(10, int(value))

    # ---- Thresholds ----

    @property
    def yellow_threshold_pct(self):
        return self._data.get("yellow_threshold_pct", 25)

    @yellow_threshold_pct.setter
    def yellow_threshold_pct(self, value):
        self._data["yellow_threshold_pct"] = int(value)

    @property
    def red_threshold_pct(self):
        return self._data.get("red_threshold_pct", 5)

    @red_threshold_pct.setter
    def red_threshold_pct(self, value):
        self._data["red_threshold_pct"] = int(value)

    @property
    def critical_threshold_pct(self):
        return self._data.get("critical_threshold_pct", 3)

    @critical_threshold_pct.setter
    def critical_threshold_pct(self, value):
        self._data["critical_threshold_pct"] = int(value)

    # ---- Endpoint mode (API key only) ----

    @property
    def endpoint_mode(self):
        val = self._data.get("endpoint_mode", "both")
        return val if val in ENDPOINT_MODES else "both"

    @endpoint_mode.setter
    def endpoint_mode(self, value):
        if value not in ENDPOINT_MODES:
            value = "both"
        self._data["endpoint_mode"] = value

    # ---- Convenience ----

    @property
    def has_oauth_token(self) -> bool:
        return bool(self.oauth_access_token)

    @property
    def is_oauth_mode(self) -> bool:
        return self.auth_mode == "oauth"
