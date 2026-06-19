"""Run blocking work off the NiceGUI event loop.

The Claude calls (``structure_*``, ``generate_cards_ai``, ``generate_quiz``) use
``asyncio.run`` internally and Playwright export uses the sync API — both must run
on a worker thread to avoid "event loop already running". Use :func:`run_blocking`
from an async click handler and ``await`` it.
"""
from __future__ import annotations

from typing import Any, Callable

from nicegui import run


async def run_blocking(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Await ``fn(*args, **kwargs)`` on a thread pool (I/O-bound work)."""
    return await run.io_bound(lambda: fn(*args, **kwargs))
