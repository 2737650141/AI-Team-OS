"""Compatibility facade for the background scheduler foundation.

M7-A4A exposes only scheduler lifecycle from this module. Semantic execution,
condition watch, notification delivery, and BackgroundJobTool are introduced
by later milestones.
"""

from app.background.scheduler import get_scheduler, shutdown_scheduler

__all__ = ["get_scheduler", "shutdown_scheduler"]
