import logging
import os
import secrets
import tkinter as tk
from tkinter import ttk, messagebox

from .api_client import AnthropicClient
from .oauth import (
    load_claude_code_credentials, generate_pkce, get_authorization_url,
    is_token_expired,
)
from .startup import is_startup_enabled, set_startup_enabled

logger = logging.getLogger("burnbar.settings")


class SettingsDialog:
    """Modal settings window (tkinter).

    Can be created from any thread -- it spins up its own Tk interpreter.
    """

    def __init__(self, config, on_save=None, parent=None):
        self.config = config
        self.on_save = on_save
        self._parent = parent
        self.root = None

    # ------------------------------------------------------------------ #
    #  Public
    # ------------------------------------------------------------------ #

    def show(self):
        logger.debug("Creating settings dialog")
        if self._parent:
            self.root = tk.Toplevel(self._parent)
        else:
            self.root = tk.Tk()
        self.root.title("BurnBar Settings")
        self.root.resizable(False, False)

        style = ttk.Style(self.root)
        for theme in ("vista", "winnative", "clam"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break

        self._build_ui()

        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"+{x}+{y}")

        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(100, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

        if self._parent:
            logger.debug("Settings dialog opened as Toplevel")
            self.root.grab_set()
            self.root.wait_window()
        else:
            logger.debug("Entering settings mainloop")
            self.root.mainloop()
        logger.debug("Settings dialog closed")

    # ------------------------------------------------------------------ #
    #  UI construction
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill="both", expand=True)

        # ---- Auth Mode ----
        ttk.Label(frame, text="Authentication:",
                  font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))

        self._auth_mode_var = tk.StringVar(value=self.config.auth_mode)
        auth_frame = ttk.Frame(frame)
        auth_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        ttk.Radiobutton(auth_frame, text="Claude.ai (OAuth)",
                        variable=self._auth_mode_var, value="oauth",
                        command=self._on_auth_mode_changed).pack(
            side="left", padx=(0, 16))
        ttk.Radiobutton(auth_frame, text="API Key",
                        variable=self._auth_mode_var, value="api_key",
                        command=self._on_auth_mode_changed).pack(side="left")

        # ---- OAuth frame ----
        self._oauth_frame = ttk.LabelFrame(frame, text="OAuth", padding=10)
        self._oauth_frame.grid(row=2, column=0, columnspan=3, sticky="ew",
                               pady=(0, 8))

        btn_row = ttk.Frame(self._oauth_frame)
        btn_row.pack(fill="x", pady=(0, 6))
        ttk.Button(btn_row, text="Import from Claude Code",
                   command=self._import_claude_code).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Login with Browser",
                   command=self._login_browser).pack(side="left")

        self._oauth_status_var = tk.StringVar()
        self._oauth_status_label = ttk.Label(
            self._oauth_frame, textvariable=self._oauth_status_var,
            foreground="gray")
        self._oauth_status_label.pack(anchor="w")
        self._update_oauth_status()

        # ---- API Key frame ----
        self._apikey_frame = ttk.LabelFrame(frame, text="API Key", padding=10)
        self._apikey_frame.grid(row=3, column=0, columnspan=3, sticky="ew",
                                pady=(0, 8))

        saved_key = self.config._data.get("api_key", "")
        env_key = os.environ.get("ANTHROPIC_API_KEY", "")

        key_row = ttk.Frame(self._apikey_frame)
        key_row.pack(fill="x", pady=(0, 4))
        self._api_key_var = tk.StringVar(value=saved_key)
        self._key_entry = ttk.Entry(
            key_row, textvariable=self._api_key_var, width=44, show="\u2022")
        self._key_entry.pack(side="left", padx=(0, 8))
        self._key_entry.bind("<Control-v>", self._paste_clipboard)
        self._key_entry.bind("<Control-V>", self._paste_clipboard)

        self._show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(key_row, text="Show", variable=self._show_var,
                        command=self._toggle_show).pack(side="left")

        if not saved_key and env_key:
            ttk.Label(self._apikey_frame,
                      text="Using ANTHROPIC_API_KEY from environment",
                      foreground="gray").pack(anchor="w")

        # ---- Endpoint Mode (API Key only) ----
        self._endpoint_frame = ttk.Frame(self._apikey_frame)
        self._endpoint_frame.pack(fill="x", pady=(8, 0))
        ttk.Label(self._endpoint_frame, text="Endpoint:").pack(side="left")
        self._endpoint_var = tk.StringVar(value=self.config.endpoint_mode)
        ttk.Combobox(self._endpoint_frame, textvariable=self._endpoint_var,
                     width=14, state="readonly",
                     values=["both", "count_tokens", "messages"]).pack(
            side="left", padx=(8, 0))

        # ---- Separator ----
        ttk.Separator(frame, orient="horizontal").grid(
            row=4, column=0, columnspan=3, sticky="ew", pady=8)

        # ---- Poll Interval ----
        ttk.Label(frame, text="Poll Interval:").grid(
            row=5, column=0, sticky="w", pady=4)
        iv_frame = ttk.Frame(frame)
        iv_frame.grid(row=5, column=1, columnspan=2, sticky="w", pady=4)
        self._interval_var = tk.StringVar(
            value=str(self.config.poll_interval_seconds))
        ttk.Combobox(iv_frame, textvariable=self._interval_var, width=8,
                     values=["30", "60", "120", "300", "600"]).pack(side="left")
        ttk.Label(iv_frame, text=" seconds").pack(side="left")

        # ---- Thresholds ----
        ttk.Separator(frame, orient="horizontal").grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(frame, text="Color Thresholds:",
                  font=("Segoe UI", 9, "bold")).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(0, 4))

        ttk.Label(frame, text="Yellow below:").grid(
            row=8, column=0, sticky="w", pady=2)
        yf = ttk.Frame(frame)
        yf.grid(row=8, column=1, columnspan=2, sticky="w", pady=2)
        self._yellow_var = tk.StringVar(
            value=str(self.config.yellow_threshold_pct))
        ttk.Spinbox(yf, from_=1, to=99,
                     textvariable=self._yellow_var, width=6).pack(side="left")
        ttk.Label(yf, text=" %").pack(side="left")

        ttk.Label(frame, text="Red below:").grid(
            row=9, column=0, sticky="w", pady=2)
        rf = ttk.Frame(frame)
        rf.grid(row=9, column=1, columnspan=2, sticky="w", pady=2)
        self._red_var = tk.StringVar(
            value=str(self.config.red_threshold_pct))
        ttk.Spinbox(rf, from_=1, to=99,
                     textvariable=self._red_var, width=6).pack(side="left")
        ttk.Label(rf, text=" %").pack(side="left")

        # ---- Startup ----
        ttk.Separator(frame, orient="horizontal").grid(
            row=10, column=0, columnspan=3, sticky="ew", pady=8)
        self._startup_var = tk.BooleanVar(value=is_startup_enabled())
        ttk.Checkbutton(frame, text="Start with Windows",
                        variable=self._startup_var).grid(
            row=11, column=0, columnspan=3, sticky="w", pady=2)

        # ---- Buttons ----
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=12, column=0, columnspan=3, pady=(20, 0))

        ttk.Button(btn_frame, text="Test", command=self._test,
                   width=10).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Save", command=self._save,
                   width=10).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Cancel", command=self._cancel,
                   width=10).pack(side="left", padx=4)

        # Apply initial visibility
        self._on_auth_mode_changed()

    # ------------------------------------------------------------------ #
    #  Auth mode switching
    # ------------------------------------------------------------------ #

    def _on_auth_mode_changed(self):
        mode = self._auth_mode_var.get()
        if mode == "oauth":
            self._oauth_frame.grid()
            self._apikey_frame.grid_remove()
        else:
            self._oauth_frame.grid_remove()
            self._apikey_frame.grid()

    def _update_oauth_status(self):
        if self.config.has_oauth_token:
            if is_token_expired(self.config.oauth_expires_at):
                self._oauth_status_var.set("Token loaded (expired -- will auto-refresh)")
                self._oauth_status_label.config(foreground="orange")
            else:
                self._oauth_status_var.set("Token loaded")
                self._oauth_status_label.config(foreground="green")
        else:
            self._oauth_status_var.set("No token -- import or login")
            self._oauth_status_label.config(foreground="gray")

    # ------------------------------------------------------------------ #
    #  OAuth actions
    # ------------------------------------------------------------------ #

    def _import_claude_code(self):
        creds = load_claude_code_credentials()
        if not creds:
            messagebox.showwarning(
                "Import",
                "Could not find Claude Code credentials.\n\n"
                "Make sure Claude Code is installed and you have "
                "logged in at least once.",
                parent=self.root)
            return

        self.config.oauth_access_token = creds.get("accessToken", "")
        self.config.oauth_refresh_token = creds.get("refreshToken", "")
        expires_at = creds.get("expiresAt", 0)
        # expiresAt may be in milliseconds
        if expires_at > 1e12:
            expires_at = int(expires_at / 1000)
        self.config.oauth_expires_at = int(expires_at)

        self._update_oauth_status()
        logger.info("Imported Claude Code credentials")
        messagebox.showinfo(
            "Import", "OAuth credentials imported from Claude Code.",
            parent=self.root)

    def _login_browser(self):
        code_verifier, code_challenge = generate_pkce()
        state = secrets.token_urlsafe(16)
        url = get_authorization_url(code_challenge, state)

        import webbrowser
        webbrowser.open(url)

        messagebox.showinfo(
            "Browser Login",
            "A browser window has been opened.\n\n"
            "Complete the login in your browser, then copy the "
            "authorization code and paste it below.",
            parent=self.root)

        # Prompt for the authorization code
        code = _ask_string(self.root, "Authorization Code",
                           "Paste the authorization code:")
        if not code:
            return

        try:
            from .oauth import exchange_code
            access_token, refresh_token, expires_at = exchange_code(
                code, code_verifier)
            self.config.oauth_access_token = access_token
            self.config.oauth_refresh_token = refresh_token
            self.config.oauth_expires_at = expires_at
            self._update_oauth_status()
            logger.info("Browser login successful")
            messagebox.showinfo(
                "Login", "Login successful! Token obtained.",
                parent=self.root)
        except Exception as e:
            logger.error("Browser login failed: %s", e)
            messagebox.showerror(
                "Login", f"Login failed:\n\n{e}", parent=self.root)

    # ------------------------------------------------------------------ #
    #  Callbacks
    # ------------------------------------------------------------------ #

    def _paste_clipboard(self, event=None):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return "break"
        try:
            self._key_entry.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        self._key_entry.insert("insert", text)
        return "break"

    def _toggle_show(self):
        self._key_entry.config(show="" if self._show_var.get() else "\u2022")

    def _test(self):
        mode = self._auth_mode_var.get()
        if mode == "oauth":
            if not self.config.oauth_access_token:
                messagebox.showwarning(
                    "Test", "Import or login to get an OAuth token first.",
                    parent=self.root)
                return
            logger.info("Testing OAuth connection")
            try:
                client = AnthropicClient(
                    auth_mode="oauth",
                    access_token=self.config.oauth_access_token)
                usage = client.check_usage()
                logger.info("OAuth test succeeded: %s", usage.summary)
                messagebox.showinfo(
                    "Test",
                    f"Connection successful!\n\n{usage.summary}",
                    parent=self.root)
            except Exception as e:
                logger.error("OAuth test failed: %s", e)
                messagebox.showerror(
                    "Test", f"Connection failed:\n\n{e}", parent=self.root)
        else:
            api_key = self._api_key_var.get().strip()
            if not api_key:
                api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                messagebox.showwarning(
                    "Test", "Enter an API key first.", parent=self.root)
                return
            endpoint_mode = self._endpoint_var.get()
            logger.info("Testing API connection (endpoint=%s)", endpoint_mode)
            try:
                usage = AnthropicClient(
                    api_key, endpoint_mode=endpoint_mode).check_usage()
                logger.info("Test succeeded: %s", usage.summary)
                messagebox.showinfo(
                    "Test",
                    f"Connection successful!\n\n{usage.summary}",
                    parent=self.root)
            except Exception as e:
                logger.error("Test failed: %s", e)
                messagebox.showerror(
                    "Test", f"Connection failed:\n\n{e}", parent=self.root)

    def _save(self):
        mode = self._auth_mode_var.get()

        if mode == "api_key":
            api_key = self._api_key_var.get().strip()
            if api_key and not api_key.startswith("sk-"):
                if not messagebox.askyesno(
                    "Warning",
                    "This key doesn't look like an Anthropic API key "
                    '(expected "sk-..." prefix).\n\nSave anyway?',
                    parent=self.root,
                ):
                    return
            self.config.api_key = api_key
            self.config.endpoint_mode = self._endpoint_var.get()

        try:
            interval = int(self._interval_var.get())
            yellow = int(self._yellow_var.get())
            red = int(self._red_var.get())
        except ValueError:
            messagebox.showerror(
                "Error", "Please enter valid numbers.", parent=self.root)
            return

        if red >= yellow:
            messagebox.showerror(
                "Error",
                "Red threshold must be lower than yellow.",
                parent=self.root,
            )
            return

        self.config.auth_mode = mode
        self.config.poll_interval_seconds = interval
        self.config.yellow_threshold_pct = yellow
        self.config.red_threshold_pct = red
        self.config.save()

        # Apply startup setting
        set_startup_enabled(self._startup_var.get())

        logger.info("Settings saved (auth_mode=%s, interval=%ds, yellow=%d%%, red=%d%%)",
                     mode, interval, yellow, red)

        self.root.destroy()
        if self.on_save:
            self.on_save()

    def _cancel(self):
        logger.debug("Settings cancelled")
        self.root.destroy()


def _ask_string(parent, title: str, prompt: str) -> str | None:
    """Simple input dialog that returns a string or None."""
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.resizable(False, False)
    dialog.grab_set()

    ttk.Label(dialog, text=prompt, padding=10).pack()
    var = tk.StringVar()
    entry = ttk.Entry(dialog, textvariable=var, width=60)
    entry.pack(padx=10, pady=(0, 10))
    entry.focus_set()

    result = [None]

    def on_ok():
        result[0] = var.get().strip()
        dialog.destroy()

    def on_cancel():
        dialog.destroy()

    entry.bind("<Return>", lambda e: on_ok())
    btn_frame = ttk.Frame(dialog)
    btn_frame.pack(pady=(0, 10))
    ttk.Button(btn_frame, text="OK", command=on_ok, width=10).pack(
        side="left", padx=4)
    ttk.Button(btn_frame, text="Cancel", command=on_cancel, width=10).pack(
        side="left", padx=4)

    dialog.transient(parent)
    dialog.wait_window()
    return result[0]
