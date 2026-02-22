"""Windows startup registration via the Run registry key."""

import logging
import os
import sys

logger = logging.getLogger("burnbar.startup")

_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_REG_NAME = "BurnBar"


def _get_launch_command() -> str:
    """Build the command string to launch BurnBar at login.

    When running as a frozen PyInstaller exe, returns the exe path directly.
    Otherwise uses pythonw.exe so no console window appears.
    """
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}"'

    # Dev mode: find main.pyw relative to the package
    pkg_dir: str = os.path.dirname(os.path.abspath(__file__))
    project_root: str = os.path.dirname(pkg_dir)
    main_pyw: str = os.path.join(project_root, "main.pyw")

    # Prefer pythonw.exe for windowless launch
    python: str = sys.executable
    if python.lower().endswith("python.exe"):
        pythonw: str = python[:-10] + "pythonw.exe"
        if os.path.exists(pythonw):
            python = pythonw

    return f'"{python}" "{main_pyw}"'


def is_startup_enabled() -> bool:
    """Check if BurnBar is registered to run at Windows startup."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, _REG_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False


def set_startup_enabled(enabled: bool) -> None:
    """Add or remove BurnBar from Windows startup."""
    if sys.platform != "win32":
        logger.warning("Startup registration only supported on Windows")
        return

    import winreg

    if enabled:
        cmd = _get_launch_command()
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, _REG_NAME, 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        logger.info("Startup enabled: %s", cmd)
    else:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _REG_KEY, 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, _REG_NAME)
            winreg.CloseKey(key)
            logger.info("Startup disabled")
        except FileNotFoundError:
            pass  # already not registered
