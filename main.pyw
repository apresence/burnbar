#!/usr/bin/env python3
"""BurnBar -- Claude usage monitor with always-on-top overlay.

Run this file directly:
    pythonw main.pyw        (no console window)
    python  main.pyw        (with console for debugging)
"""

import logging
import os
import sys

# Ensure the project root is on the path so `burnbar` can be imported
# regardless of the working directory.
_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)


def _setup_logging():
    """Configure file logging under <project_root>/log/."""
    log_dir = os.path.join(_ROOT, "log")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "burnbar.log")

    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root_logger = logging.getLogger("burnbar")
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)

    # Also log to stderr when running with python.exe (not pythonw)
    if sys.executable and not sys.executable.lower().endswith("pythonw.exe"):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(
            "%(levelname)-8s  %(name)s  %(message)s"))
        root_logger.addHandler(console)

    return logging.getLogger("burnbar.main")


def _single_instance_check() -> bool:
    """Return False if another instance is already running (Windows only)."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW(None, False, "BurnBar_SingleInstance_Mutex")
        return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def main():
    logger = _setup_logging()
    logger.info("BurnBar starting")

    if not _single_instance_check():
        logger.info("Another instance already running -- exiting")
        return

    try:
        from burnbar.app import BurnBarApp
        app = BurnBarApp()
        app.run()
    except Exception:
        logger.exception("Fatal error in BurnBarApp")
        raise


if __name__ == "__main__":
    main()
