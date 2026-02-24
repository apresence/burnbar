import json
import os
import base64
import ctypes
import ctypes.wintypes
import logging
import typing as tp  # type: ignore[unusedImport]

from pathlib import Path

logger: logging.Logger = logging.getLogger("burnbar.config")

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
    "overlay_scale": 1.0,
}


# Keys that get encrypted with DPAPI before writing to disk
_SENSITIVE_KEYS: list[str] = ["api_key", "oauth_access_token", "oauth_refresh_token"]


class _DataBlob(ctypes.Structure):
    _fields_: list[tuple[str, tp.Any]] = [  # type: ignore[reportIncompatibleVariableOverride]
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


_DPAPI_PREFIX: str = "{DPAPI}"


def _dpapi_encrypt(plaintext: str) -> str:
    """Encrypt a string with Windows DPAPI, return prefixed base64 result."""
    if not plaintext:
        return ""
    data: bytes = plaintext.encode("utf-8")
    blob_in: _DataBlob = _DataBlob(len(data), ctypes.create_string_buffer(data, len(data)))
    blob_out: _DataBlob = _DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(  # type: ignore[union-attr]
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptProtectData failed")
    encrypted: bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)  # type: ignore[union-attr]
    return _DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")


def _dpapi_decrypt(value: str) -> str:
    """Decrypt a DPAPI-prefixed base64 blob back to plaintext."""
    if not value:
        return ""
    b64_cipher: str = value.removeprefix(_DPAPI_PREFIX)
    data: bytes = base64.b64decode(b64_cipher)
    blob_in: _DataBlob = _DataBlob(len(data), ctypes.create_string_buffer(data, len(data)))
    blob_out: _DataBlob = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(  # type: ignore[union-attr]
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise OSError("CryptUnprotectData failed")
    plaintext: bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)  # type: ignore[union-attr]
    return plaintext.decode("utf-8")


class Config:
    def __init__(self):
        self._data = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r") as f:
                    self._data.update(json.load(f))
                # Decrypt encrypted fields; encrypt any plaintext on the spot
                needs_save: bool = False
                for key in _SENSITIVE_KEYS:
                    val: str = self._data.get(key, "")
                    if not val:
                        continue
                    if val.startswith(_DPAPI_PREFIX):
                        try:
                            self._data[key] = _dpapi_decrypt(val)
                        except OSError:
                            logger.warning("Failed to decrypt %s", key)
                            self._data[key] = ""
                    else:
                        # Plaintext found -- encrypt immediately
                        needs_save = True
                if needs_save:
                    self.save()
        except (json.JSONDecodeError, OSError):
            pass

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        out: dict[str, tp.Any] = dict(self._data)
        # Encrypt sensitive fields
        for key in _SENSITIVE_KEYS:
            val: str = out.get(key, "")
            if val:
                try:
                    out[key] = _dpapi_encrypt(val)
                except OSError:
                    logger.warning("Failed to encrypt %s, storing plaintext", key)
        with open(CONFIG_FILE, "w") as f:
            json.dump(out, f, indent=2)

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
