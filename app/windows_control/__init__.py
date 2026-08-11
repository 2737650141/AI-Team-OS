"""M5-A controlled Windows desktop observation and action layer."""

from typing import Any

__all__ = ["WindowsComputerService"]


def __getattr__(name: str) -> Any:
    """Keep the public convenience import without eagerly creating a service cycle."""
    if name == "WindowsComputerService":
        from app.windows_control.service import WindowsComputerService

        return WindowsComputerService
    raise AttributeError(name)
