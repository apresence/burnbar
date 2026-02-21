import time
import queue
import logging
import typing as tp  # type: ignore[unusedImport]
import tkinter as tk
import threading

logger: logging.Logger = logging.getLogger("burnbar.overlay")

# Bar labels and base layout constants (reference at scale 1.0)
_BAR_LABELS: list[str] = ["Sess", "Week", "Sonn"]
_BASE_WIDTH: int = 180
_BASE_BAR_HEIGHT: int = 14
_BASE_BAR_GAP: int = 2
_BASE_PAD: int = 3
_BASE_HEIGHT: int = _BASE_PAD * 2 + _BASE_BAR_HEIGHT * 3 + _BASE_BAR_GAP * 2
_MIN_WIDTH: int = 120
_MAX_WIDTH: int = 600
_GRIP_SIZE: int = 12
_BG: str = "#1a1a1a"
_BAR_BG: str = "#333333"
_BORDER: str = "#555555"
_TEXT_COLOR: str = "#ffffff"

# Color thresholds (utilization 0.0-1.0)
_GREEN: str = "#22c55e"
_YELLOW: str = "#eab308"
_RED: str = "#ef4444"


def _bar_color(utilization: float, yellow_thresh: float, red_thresh: float) -> str:
    """Return fill color for a bar based on utilization thresholds."""
    if utilization >= red_thresh:
        return _RED
    if utilization >= yellow_thresh:
        return _YELLOW
    return _GREEN


def _format_countdown(reset_epoch: int, now: int) -> str:
    """Format seconds until reset as compact countdown: Xd, Xh, or Xm."""
    if reset_epoch <= 0:
        return ""
    remaining: int = reset_epoch - now
    if remaining <= 0:
        return "0m"
    if remaining >= 86400:
        return f"{remaining // 86400}d"
    if remaining >= 3600:
        return f"{remaining // 3600}h"
    return f"{max(1, remaining // 60)}m"


class UsageOverlay:
    """Always-on-top mini window showing 3 usage bars with right-click menu."""

    def __init__(self, config: tp.Any) -> None:
        self.config: tp.Any = config
        self._root: tp.Optional[tk.Tk] = None
        self._canvas: tp.Optional[tk.Canvas] = None
        self._drag_x: int = 0
        self._drag_y: int = 0
        self._ready: threading.Event = threading.Event()
        self._flash_bars: list[bool] = [False, False, False]
        self._flash_visible: bool = True
        self._flash_critical: bool = False
        self._flash_dismissed: list[bool] = [False, False, False]
        self._queue: queue.Queue[tp.Callable[[], None]] = queue.Queue()
        self._tooltip: tp.Optional[tk.Toplevel] = None
        self._tooltip_after_id: tp.Optional[str] = None
        self._dragging: bool = False
        self._resizing: bool = False
        self._resize_start_x: int = 0
        self._resize_start_width: int = 0

        # Last draw params for redraw on resize
        self._last_draw: tp.Optional[tuple[
            tuple[float, float, float], float, float, tuple[int, int, int]
        ]] = None

        # Scaled layout vars (set by _apply_scale)
        self._scale: float = 1.0
        self._width: int = _BASE_WIDTH
        self._height: int = _BASE_HEIGHT
        self._bar_height: int = _BASE_BAR_HEIGHT
        self._bar_gap: int = _BASE_BAR_GAP
        self._pad: int = _BASE_PAD
        self._font_size: int = 8

        # Callbacks wired by the app
        self.on_refresh: tp.Optional[tp.Callable[[], None]] = None
        self.on_settings: tp.Optional[tp.Callable[[], None]] = None
        self.on_exit: tp.Optional[tp.Callable[[], None]] = None
        self.get_status_lines: tp.Optional[tp.Callable[[], list[str]]] = None
        self.get_tooltip_text: tp.Optional[tp.Callable[[], str]] = None

    @property
    def tk_root(self) -> tp.Optional[tk.Tk]:
        """Expose the Tk root for child windows like settings."""
        return self._root

    def _apply_scale(self, scale: float) -> None:
        """Recalculate layout vars from scale and resize the canvas."""
        self._scale = scale
        self._width = int(_BASE_WIDTH * scale)
        self._bar_height = max(8, int(_BASE_BAR_HEIGHT * scale))
        self._bar_gap = max(1, int(_BASE_BAR_GAP * scale))
        self._pad = max(2, int(_BASE_PAD * scale))
        self._height = self._pad * 2 + self._bar_height * 3 + self._bar_gap * 2
        self._font_size = max(6, int(8 * scale))
        if self._canvas:
            self._canvas.configure(width=self._width, height=self._height)
            if self._last_draw:
                self._draw(*self._last_draw)
            else:
                self._draw_loading()

    def _init_window(self) -> None:
        """Create the overlay window and canvas."""
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.85)
        self._root.configure(bg=_BG)

        # Apply saved scale before creating canvas
        saved_scale: float = float(self.config._data.get("overlay_scale", 1.0))
        self._apply_scale(saved_scale)

        self._canvas = tk.Canvas(
            self._root,
            width=self._width,
            height=self._height,
            bg=_BG,
            highlightthickness=1,
            highlightbackground=_BORDER,
        )
        self._canvas.pack()

        # Dragging (left-click)
        self._canvas.bind("<Button-1>", self._on_drag_start)
        self._canvas.bind("<B1-Motion>", self._on_drag_motion)
        self._canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self._canvas.bind("<Double-Button-1>", self._on_double_click)

        # Cursor hint for resize grip
        self._canvas.bind("<Motion>", self._on_mouse_move)

        # Right-click context menu
        self._canvas.bind("<Button-3>", self._on_right_click)

        # Hover tooltip
        self._canvas.bind("<Enter>", self._on_hover_enter)
        self._canvas.bind("<Leave>", self._on_hover_leave)

        # Position: load saved or auto-place above taskbar, bottom-right
        ox: int = self.config._data.get("overlay_x", -1)
        oy: int = self.config._data.get("overlay_y", -1)
        if ox < 0 or oy < 0:
            self._root.update_idletasks()
            sw: int = self._root.winfo_screenwidth()
            sh: int = self._root.winfo_screenheight()
            # Place above taskbar (assume ~40px taskbar)
            ox = sw - self._width - 3
            oy = sh - self._height - 50
        self._root.geometry(f"+{ox}+{oy}")

        # Show labels only until first data arrives
        self._draw_loading()
        self._ready.set()
        logger.info("Overlay window started at (%d, %d), scale=%.2f", ox, oy, self._scale)

    def run_mainloop(self, alive_check: tp.Callable[[], bool]) -> None:
        """Run the overlay event loop in the calling thread.

        Manually pumps tkinter events instead of entering mainloop().
        Worker threads post callables to self._queue; we drain them here.
        """
        logger.info("Overlay starting (main thread)")
        self._init_window()
        try:
            while alive_check():
                # Drain queued callbacks from worker threads
                while not self._queue.empty():
                    try:
                        fn: tp.Callable[[], None] = self._queue.get_nowait()
                        fn()
                    except queue.Empty:
                        break
                try:
                    self._root.update()  # type: ignore[union-attr]
                except tk.TclError:
                    logger.info("Overlay window destroyed, exiting loop")
                    break
                time.sleep(0.02)
        finally:
            logger.info("Overlay shutting down")
            self._shutdown()

    def schedule_update(
        self,
        utilizations: tuple[float, float, float],
        yellow_thresh: float,
        red_thresh: float,
        resets: tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        """Thread-safe update from the poll thread."""
        if self._root and self._ready.is_set():
            logger.debug("Queuing overlay update: %.2f, %.2f, %.2f",
                         *utilizations)
            self._queue.put(
                lambda u=utilizations, y=yellow_thresh, r=red_thresh, rs=resets:
                    self._draw(u, y, r, rs))

    def schedule_flash(self, flash_bars: list[bool], critical: bool) -> None:
        """Thread-safe flash state update."""
        if self._root and self._ready.is_set():
            self._queue.put(
                lambda fb=list(flash_bars), c=critical:
                    self._set_flash(fb, c))

    def stop(self) -> None:
        """Destroy the overlay window (thread-safe)."""
        if self._root:
            self._queue.put(self._shutdown)

    # ------------------------------------------------------------------ #
    #  Right-click context menu
    # ------------------------------------------------------------------ #

    def _on_right_click(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """Show context menu on right-click."""
        # Cancel any pending tooltip so it doesn't pop over the menu
        if self._tooltip_after_id:
            self._root.after_cancel(self._tooltip_after_id)  # type: ignore[union-attr]
            self._tooltip_after_id = None
        self._hide_tooltip()

        menu: tk.Menu = tk.Menu(self._root, tearoff=0)

        # Status lines (disabled, info only)
        if self.get_status_lines:
            lines: list[str] = self.get_status_lines()
            for line in lines:
                menu.add_command(label=line, state="disabled")
            if lines:
                menu.add_separator()

        # Dismiss flash option (only when bars are actively flashing)
        has_active_flash: bool = any(
            fb and not fd
            for fb, fd in zip(self._flash_bars, self._flash_dismissed))
        if has_active_flash:
            menu.add_command(label="Dismiss Flash",
                             command=self._menu_dismiss_flash)
            menu.add_separator()

        # Action items
        menu.add_command(label="Refresh Now", command=self._menu_refresh)
        menu.add_command(label="Settings...", command=self._menu_settings)
        if self._scale != 1.0:
            menu.add_command(label="Reset Size", command=self._menu_reset_size)
        menu.add_separator()
        menu.add_command(label="Exit", command=self._menu_exit)

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _menu_refresh(self) -> None:
        if self.on_refresh:
            self.on_refresh()

    def _menu_settings(self) -> None:
        if self.on_settings:
            self.on_settings()

    def _menu_reset_size(self) -> None:
        self._apply_scale(1.0)
        self.config._data["overlay_scale"] = 1.0

    def _menu_dismiss_flash(self) -> None:
        self._flash_dismissed = [
            fd or fb for fd, fb in zip(self._flash_dismissed, self._flash_bars)]
        if self._last_draw:
            self._draw(*self._last_draw)

    def _menu_exit(self) -> None:
        if self.on_exit:
            self.on_exit()

    # ------------------------------------------------------------------ #
    #  Hover tooltip
    # ------------------------------------------------------------------ #

    def _on_hover_enter(self, event: tk.Event) -> None:  # type: ignore[type-arg, reportUnusedParameter]
        """Schedule tooltip after a short delay."""
        if self._dragging:
            return
        self._tooltip_after_id = self._root.after(  # type: ignore[union-attr]
            400, self._show_tooltip)

    def _on_hover_leave(self, event: tk.Event) -> None:  # type: ignore[type-arg, reportUnusedParameter]
        """Cancel pending tooltip and hide any visible one."""
        if self._tooltip_after_id:
            self._root.after_cancel(self._tooltip_after_id)  # type: ignore[union-attr]
            self._tooltip_after_id = None
        self._hide_tooltip()

    def _show_tooltip(self) -> None:
        """Display a tooltip window with per-window usage and reset times."""
        self._hide_tooltip()
        if not self.get_tooltip_text or not self._root:
            return
        text: str = self.get_tooltip_text()
        if not text:
            return

        tw: tk.Toplevel = tk.Toplevel(self._root)
        tw.overrideredirect(True)
        tw.attributes("-topmost", True)

        label: tk.Label = tk.Label(
            tw,
            text=text,
            justify="left",
            background="#ffffe0",
            foreground="#000000",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 8),
            padx=6,
            pady=4,
        )
        label.pack()

        # Position above the overlay
        tw.update_idletasks()
        x: int = self._root.winfo_x()
        y: int = self._root.winfo_y() - tw.winfo_reqheight() - 4
        tw.geometry(f"+{x}+{y}")
        self._tooltip = tw

    def _hide_tooltip(self) -> None:
        if self._tooltip:
            self._tooltip.destroy()
            self._tooltip = None

    # ------------------------------------------------------------------ #
    #  Drawing
    # ------------------------------------------------------------------ #

    def _draw_loading(self) -> None:
        """Draw labels only with no bars -- shown before first data arrives."""
        if self._canvas is None:
            return
        c: tk.Canvas = self._canvas
        c.delete("all")

        label_width: int = int(32 * self._scale)
        font: tuple[str, int] = ("Segoe UI", self._font_size)
        for i, label in enumerate(_BAR_LABELS):
            y0: int = self._pad + i * (self._bar_height + self._bar_gap)
            y1: int = y0 + self._bar_height
            text_y: int = (y0 + y1) // 2
            c.create_text(self._pad + label_width // 2, text_y, text=label,
                          fill=_TEXT_COLOR, font=font)

    def _draw(
        self,
        utilizations: tuple[float, float, float],
        yellow_thresh: float,
        red_thresh: float,
        resets: tuple[int, int, int] = (0, 0, 0),
    ) -> None:
        """Redraw the 3 bars on the canvas."""
        if self._canvas is None:
            return
        self._last_draw = (utilizations, yellow_thresh, red_thresh, resets)
        c: tk.Canvas = self._canvas
        c.delete("all")

        label_width: int = int(32 * self._scale)
        right_width: int = int(30 * self._scale)
        bar_x0: int = self._pad + label_width
        bar_x1: int = self._width - self._pad - right_width
        font: tuple[str, int] = ("Segoe UI", self._font_size)

        now: int = int(time.time())
        for i, (util, label, reset_epoch) in enumerate(
                zip(utilizations, _BAR_LABELS, resets)):
            y0: int = self._pad + i * (self._bar_height + self._bar_gap)
            y1: int = y0 + self._bar_height

            # Bar background
            c.create_rectangle(bar_x0, y0, bar_x1, y1, fill=_BAR_BG, outline="")

            # Bar fill (skip when bar is flash-blinking off)
            flash_off: bool = (self._flash_bars[i]
                               and not self._flash_dismissed[i]
                               and not self._flash_visible)
            fill_w: int = int((bar_x1 - bar_x0) * min(1.0, max(0.0, util)))
            if fill_w > 0 and not flash_off:
                color: str = _bar_color(util, yellow_thresh, red_thresh)
                c.create_rectangle(bar_x0, y0, bar_x0 + fill_w, y1,
                                   fill=color, outline="")

            # Label (left)
            text_y: int = (y0 + y1) // 2
            c.create_text(self._pad + label_width // 2, text_y, text=label,
                          fill=_TEXT_COLOR, font=font)

            # Reset countdown (right)
            right_str: str = _format_countdown(reset_epoch, now)
            c.create_text(bar_x1 + right_width // 2, text_y, text=right_str,
                          fill=_TEXT_COLOR, font=font)

    # ------------------------------------------------------------------ #
    #  Flashing
    # ------------------------------------------------------------------ #

    def _set_flash(self, flash_bars: list[bool], critical: bool) -> None:
        """Update flash state; called on the tk thread."""
        was_any: bool = any(self._flash_bars)
        # Clear dismissed state for bars that stopped flashing (usage reset)
        for i in range(3):
            if self._flash_bars[i] and not flash_bars[i]:
                self._flash_dismissed[i] = False
        self._flash_bars = list(flash_bars)
        self._flash_critical = critical
        now_any: bool = any(flash_bars)

        if now_any and not was_any:
            interval: int = 500 if critical else 1000
            self._flash_visible = True
            self._flash_tick(interval)
        elif not now_any and was_any:
            self._flash_visible = True
            if self._last_draw:
                self._draw(*self._last_draw)

    def _flash_tick(self, interval: int) -> None:
        """Toggle bar fill visibility."""
        if not any(self._flash_bars) or not self._root:
            return
        self._flash_visible = not self._flash_visible
        interval = 500 if self._flash_critical else 1000
        if self._last_draw:
            self._draw(*self._last_draw)
        self._root.after(interval, self._flash_tick, interval)

    # ------------------------------------------------------------------ #
    #  Dragging
    # ------------------------------------------------------------------ #

    def _in_grip(self, x: int, y: int) -> bool:
        """Check if coordinates are within the bottom-right resize grip."""
        return x >= self._width - _GRIP_SIZE and y >= self._height - _GRIP_SIZE

    def _on_mouse_move(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """Change cursor when hovering over the resize grip."""
        if self._canvas is None:
            return
        if self._in_grip(event.x, event.y):
            self._canvas.configure(cursor="bottom_right_corner")
        else:
            self._canvas.configure(cursor="")

    def _on_drag_start(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._hide_tooltip()
        if self._tooltip_after_id:
            self._root.after_cancel(self._tooltip_after_id)  # type: ignore[union-attr]
            self._tooltip_after_id = None
        if self._in_grip(event.x, event.y):
            self._resizing = True
            self._resize_start_x = event.x_root
            self._resize_start_width = self._width
        else:
            self._dragging = True
            self._drag_x = event.x
            self._drag_y = event.y

    def _on_drag_end(self, event: tk.Event) -> None:  # type: ignore[type-arg, reportUnusedParameter]
        if self._resizing:
            self._resizing = False
            self.config._data["overlay_scale"] = round(self._scale, 3)
        self._dragging = False

    def _on_drag_motion(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        if not self._root:
            return
        if self._resizing:
            dx: int = event.x_root - self._resize_start_x
            new_width: int = max(_MIN_WIDTH, min(_MAX_WIDTH, self._resize_start_width + dx))
            new_scale: float = new_width / _BASE_WIDTH
            self._apply_scale(new_scale)
            return
        x: int = self._root.winfo_x() + event.x - self._drag_x
        y: int = self._root.winfo_y() + event.y - self._drag_y
        self._root.geometry(f"+{x}+{y}")
        # Persist position
        self.config._data["overlay_x"] = x
        self.config._data["overlay_y"] = y

    def _on_double_click(self, event: tk.Event) -> None:  # type: ignore[type-arg, reportUnusedParameter]
        """Reset to default scale on double-click."""
        if self._scale != 1.0:
            self._apply_scale(1.0)
            self.config._data["overlay_scale"] = 1.0

    # ------------------------------------------------------------------ #
    #  Shutdown
    # ------------------------------------------------------------------ #

    def _shutdown(self) -> None:
        """Save position and destroy."""
        if self._root:
            try:
                self.config.save()
            except Exception:
                pass
            self._root.destroy()
            self._root = None
