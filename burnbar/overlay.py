import time
import queue
import logging
import typing as tp  # type: ignore[unusedImport]
import tkinter as tk
import threading

logger: logging.Logger = logging.getLogger("burnbar.overlay")

# Bar labels and layout constants
_BAR_LABELS: list[str] = ["Sess", "Week", "Sonn"]
_WIDTH: int = 180
_BAR_HEIGHT: int = 14
_BAR_GAP: int = 2
_PAD: int = 3
_HEIGHT: int = _PAD * 2 + _BAR_HEIGHT * 3 + _BAR_GAP * 2
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
        self._flash_active: bool = False
        self._flash_visible: bool = True
        self._queue: queue.Queue[tp.Callable[[], None]] = queue.Queue()
        self._tooltip: tp.Optional[tk.Toplevel] = None
        self._tooltip_after_id: tp.Optional[str] = None
        self._dragging: bool = False

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

    def _init_window(self) -> None:
        """Create the overlay window and canvas."""
        self._root = tk.Tk()
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.85)
        self._root.configure(bg=_BG)

        self._canvas = tk.Canvas(
            self._root,
            width=_WIDTH,
            height=_HEIGHT,
            bg=_BG,
            highlightthickness=1,
            highlightbackground=_BORDER,
        )
        self._canvas.pack()

        # Dragging (left-click)
        self._canvas.bind("<Button-1>", self._on_drag_start)
        self._canvas.bind("<B1-Motion>", self._on_drag_motion)
        self._canvas.bind("<ButtonRelease-1>", self._on_drag_end)

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
            ox = sw - _WIDTH - 3
            oy = sh - _HEIGHT - 50
        self._root.geometry(f"+{ox}+{oy}")

        # Show labels only until first data arrives
        self._draw_loading()
        self._ready.set()
        logger.info("Overlay window started at (%d, %d)", ox, oy)

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

    def schedule_flash(self, active: bool, critical: bool) -> None:
        """Thread-safe flash state update."""
        if self._root and self._ready.is_set():
            self._queue.put(
                lambda a=active, c=critical:
                    self._set_flash(a, c))

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

        # Action items
        menu.add_command(label="Refresh Now", command=self._menu_refresh)
        menu.add_command(label="Settings...", command=self._menu_settings)
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

    def _menu_exit(self) -> None:
        if self.on_exit:
            self.on_exit()

    # ------------------------------------------------------------------ #
    #  Hover tooltip
    # ------------------------------------------------------------------ #

    def _on_hover_enter(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """Schedule tooltip after a short delay."""
        if self._dragging:
            return
        self._tooltip_after_id = self._root.after(  # type: ignore[union-attr]
            400, self._show_tooltip)

    def _on_hover_leave(self, event: tk.Event) -> None:  # type: ignore[type-arg]
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

        label_width: int = 32
        for i, label in enumerate(_BAR_LABELS):
            y0: int = _PAD + i * (_BAR_HEIGHT + _BAR_GAP)
            y1: int = y0 + _BAR_HEIGHT
            text_y: int = (y0 + y1) // 2
            c.create_text(_PAD + label_width // 2, text_y, text=label,
                          fill=_TEXT_COLOR, font=("Segoe UI", 8))

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
        c: tk.Canvas = self._canvas
        c.delete("all")

        label_width: int = 32
        right_width: int = 30
        bar_x0: int = _PAD + label_width
        bar_x1: int = _WIDTH - _PAD - right_width

        now: int = int(time.time())
        for i, (util, label, reset_epoch) in enumerate(
                zip(utilizations, _BAR_LABELS, resets)):
            y0: int = _PAD + i * (_BAR_HEIGHT + _BAR_GAP)
            y1: int = y0 + _BAR_HEIGHT

            # Bar background
            c.create_rectangle(bar_x0, y0, bar_x1, y1, fill=_BAR_BG, outline="")

            # Bar fill
            fill_w: int = int((bar_x1 - bar_x0) * min(1.0, max(0.0, util)))
            if fill_w > 0:
                color: str = _bar_color(util, yellow_thresh, red_thresh)
                c.create_rectangle(bar_x0, y0, bar_x0 + fill_w, y1,
                                   fill=color, outline="")

            # Label (left)
            text_y: int = (y0 + y1) // 2
            c.create_text(_PAD + label_width // 2, text_y, text=label,
                          fill=_TEXT_COLOR, font=("Segoe UI", 8))

            # Reset countdown (right)
            right_str: str = _format_countdown(reset_epoch, now)
            c.create_text(bar_x1 + right_width // 2, text_y, text=right_str,
                          fill=_TEXT_COLOR, font=("Segoe UI", 8))

    # ------------------------------------------------------------------ #
    #  Flashing
    # ------------------------------------------------------------------ #

    def _set_flash(self, active: bool, critical: bool) -> None:
        """Update flash state; called on the tk thread."""
        was_active: bool = self._flash_active
        self._flash_active = active

        if active and not was_active:
            interval: int = 500 if critical else 1000
            self._flash_visible = True
            self._flash_tick(interval)
        elif not active and was_active:
            self._flash_visible = True
            self._root.attributes("-alpha", 0.85)  # type: ignore[union-attr]

    def _flash_tick(self, interval: int) -> None:
        """Toggle visibility via alpha channel."""
        if not self._flash_active or not self._root:
            return
        self._flash_visible = not self._flash_visible
        alpha: float = 0.85 if self._flash_visible else 0.0
        self._root.attributes("-alpha", alpha)
        self._root.after(interval, self._flash_tick, interval)

    # ------------------------------------------------------------------ #
    #  Dragging
    # ------------------------------------------------------------------ #

    def _on_drag_start(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._dragging = True
        self._hide_tooltip()
        if self._tooltip_after_id:
            self._root.after_cancel(self._tooltip_after_id)  # type: ignore[union-attr]
            self._tooltip_after_id = None
        self._drag_x = event.x
        self._drag_y = event.y

    def _on_drag_end(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self._dragging = False

    def _on_drag_motion(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        if not self._root:
            return
        x: int = self._root.winfo_x() + event.x - self._drag_x
        y: int = self._root.winfo_y() + event.y - self._drag_y
        self._root.geometry(f"+{x}+{y}")
        # Persist position
        self.config._data["overlay_x"] = x
        self.config._data["overlay_y"] = y

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
