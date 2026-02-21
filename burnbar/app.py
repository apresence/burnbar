import logging
import threading
import time
import typing as tp  # type: ignore[unusedImport]

from datetime import datetime

from .api_client import AnthropicClient, ApiError, UnifiedUsageInfo
from .config import Config
from .oauth import is_token_expired, refresh_access_token, load_claude_code_credentials
from .overlay import UsageOverlay
from .settings_dialog import SettingsDialog

logger: logging.Logger = logging.getLogger("burnbar.app")


class BurnBarApp:
    """Application that monitors Anthropic API token usage."""

    def __init__(self) -> None:
        self.config: Config = Config()
        self.usage: tp.Any = None
        self.error: tp.Optional[str] = None
        self.last_update: str = ""
        self.running: bool = False
        self._overlay: UsageOverlay = UsageOverlay(self.config)

    # ------------------------------------------------------------------ #
    #  Lifecycle
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """Block the calling thread and run the application."""
        has_creds: bool = self._has_credentials()
        logger.info("run(): auth_mode=%s, credentials_present=%s",
                     self.config.auth_mode, has_creds)

        if self.config.is_oauth_mode and not self.config.has_oauth_token:
            self._try_auto_import_claude_code()

        self.running = True

        # Wire overlay menu callbacks
        self._overlay.on_refresh = self._on_refresh
        self._overlay.on_settings = self._on_settings
        self._overlay.on_exit = self._on_exit
        self._overlay.get_status_lines = self._get_status_lines
        self._overlay.get_tooltip_text = self._get_tooltip_text

        # Start poll loop in a background thread
        self._poll_thread: threading.Thread = threading.Thread(
            target=self._poll_loop, daemon=True)
        self._poll_thread.start()

        if not self._has_credentials():
            logger.info("No credentials configured; waiting for user to open Settings")

        # Run the overlay in the main thread (tkinter needs it on Windows)
        logger.info("Starting overlay (main thread)")
        try:
            self._overlay.run_mainloop(alive_check=lambda: self.running)
        except KeyboardInterrupt:
            logger.info("Ctrl+C received, shutting down")
        finally:
            self.running = False
        logger.info("Application exited")

    # ------------------------------------------------------------------ #
    #  Polling
    # ------------------------------------------------------------------ #

    def _poll_loop(self) -> None:
        logger.debug("Poll loop started")
        time.sleep(1)
        while self.running:
            if self._has_credentials():
                self._refresh()
            else:
                logger.debug("Poll loop: no credentials, skipping refresh")
            interval: int = max(10, self.config.poll_interval_seconds)
            for _ in range(interval * 10):
                if not self.running:
                    return
                time.sleep(0.1)

    def _has_credentials(self) -> bool:
        if self.config.is_oauth_mode:
            return self.config.has_oauth_token
        return bool(self.config.api_key)

    def _try_auto_import_claude_code(self) -> None:
        """Try to automatically import credentials from Claude Code on startup."""
        creds: tp.Optional[dict[str, tp.Any]] = load_claude_code_credentials()
        if not creds:
            return
        self.config.oauth_access_token = creds.get("accessToken", "")
        self.config.oauth_refresh_token = creds.get("refreshToken", "")
        expires_at: tp.Any = creds.get("expiresAt", 0)
        if expires_at > 1e12:
            expires_at = int(expires_at / 1000)
        self.config.oauth_expires_at = int(expires_at)
        self.config.save()
        logger.info("Auto-imported OAuth credentials from Claude Code")

    # ------------------------------------------------------------------ #
    #  OAuth token management
    # ------------------------------------------------------------------ #

    def _ensure_valid_oauth_token(self) -> None:
        """Refresh the OAuth token if it's expired or about to expire."""
        if not is_token_expired(self.config.oauth_expires_at):
            return

        refresh_token: str = self.config.oauth_refresh_token
        if not refresh_token:
            logger.warning("OAuth token expired and no refresh token available")
            raise ApiError("OAuth token expired -- re-login in Settings")

        logger.info("OAuth token expired, refreshing...")
        try:
            new_access: str
            new_refresh: str
            new_expires: int
            new_access, new_refresh, new_expires = refresh_access_token(
                refresh_token)
            self.config.oauth_access_token = new_access
            self.config.oauth_refresh_token = new_refresh
            self.config.oauth_expires_at = new_expires
            self.config.save()
            logger.info("OAuth token refreshed successfully")
        except Exception as exc:
            logger.error("OAuth token refresh failed: %s", exc)
            raise ApiError(f"Token refresh failed: {exc}")

    # ------------------------------------------------------------------ #
    #  Refresh logic
    # ------------------------------------------------------------------ #

    def _refresh(self) -> None:
        logger.debug("Refreshing usage data...")
        try:
            if self.config.is_oauth_mode:
                self._ensure_valid_oauth_token()
                client: AnthropicClient = AnthropicClient(
                    auth_mode="oauth",
                    access_token=self.config.oauth_access_token,
                )
            else:
                client = AnthropicClient(
                    api_key=self.config.api_key,
                    endpoint_mode=self.config.endpoint_mode,
                )

            self.usage = client.check_usage()
            self.error = None

            pct: float = self.usage.percentage
            logger.info("Usage: %.1f%% -- %s", pct, self.usage.summary)
            self.last_update = datetime.now().strftime("%I:%M:%S %p").lstrip("0")

            # Determine flash state
            flash_active: bool = False
            flash_critical: bool = False
            critical: int = getattr(self.config, "critical_threshold_pct", 3)
            if pct <= critical:
                flash_active = True
                flash_critical = True
            elif pct <= (self.config.red_threshold_pct + 0.1):
                flash_active = True

            # Update overlay
            yellow_util: float = 1.0 - (self.config.yellow_threshold_pct / 100.0)
            red_util: float = 1.0 - (self.config.red_threshold_pct / 100.0)
            if isinstance(self.usage, UnifiedUsageInfo):
                resets: tuple[int, int, int] = (
                    self.usage.reset_5h,
                    self.usage.reset_7d,
                    self.usage.reset_7d_sonnet,
                )
                self._overlay.schedule_update(
                    self.usage.utilizations, yellow_util, red_util, resets)
            else:
                util: float = 1.0 - (pct / 100.0)
                self._overlay.schedule_update(
                    (util, util, util), yellow_util, red_util)
            self._overlay.schedule_flash(flash_active, flash_critical)

        except (ApiError, Exception) as exc:
            logger.error("Refresh failed: %s", exc)
            self.error = str(exc)[:80]
            self.usage = None
            self._overlay.schedule_flash(False, False)

    # ------------------------------------------------------------------ #
    #  Status lines for overlay context menu
    # ------------------------------------------------------------------ #

    def _get_status_lines(self) -> list[str]:
        """Return status lines for the overlay's right-click menu."""
        lines: list[str] = []
        if self.error:
            lines.append(f"Error: {self.error}")
        elif self.usage is None:
            if not self._has_credentials():
                mode: str = "OAuth token" if self.config.is_oauth_mode else "API key"
                lines.append(f"{mode} not set -- open Settings")
            else:
                lines.append("Connecting...")
        else:
            lines.append(f"{self.usage.percentage:.0f}% capacity remaining")
            if self.usage.detail_line:
                lines.append(self.usage.detail_line)
            if isinstance(self.usage, UnifiedUsageInfo):
                if self.usage.has_reset:
                    lines.append(f"Resets: {self.usage.reset_display}")
            elif self.usage.reset_time:
                lines.append(f"Resets: {self.usage.reset_display}")
        if self.last_update:
            lines.append(f"Updated: {self.last_update}")
        return lines

    def _get_tooltip_text(self) -> str:
        """Return tooltip text showing per-window usage and reset times."""
        if self.error:
            return f"BurnBar -- {self.error}"
        if self.usage is None:
            return "BurnBar -- Connecting..."
        text: str = self.usage.tooltip()
        if self.last_update:
            text += f"\nUpdated: {self.last_update}"
        return text

    # ------------------------------------------------------------------ #
    #  Menu callbacks
    # ------------------------------------------------------------------ #

    def _on_refresh(self) -> None:
        threading.Thread(target=self._refresh, daemon=True).start()

    def _on_settings(self) -> None:
        logger.info("Opening settings dialog")
        dialog: SettingsDialog = SettingsDialog(
            self.config, on_save=self._on_settings_saved)
        threading.Thread(target=dialog.show, daemon=True).start()

    def _on_settings_saved(self) -> None:
        threading.Thread(target=self._refresh, daemon=True).start()

    def _on_exit(self) -> None:
        logger.info("Exit requested")
        self.running = False
        self._overlay.stop()
