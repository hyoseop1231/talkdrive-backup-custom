"""Shared utilities: retry, sanitize, verify_download, state management."""

import functools
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# --- Retry decorator ---

def retry(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Retry decorator with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        delay: Initial delay between retries in seconds.
        backoff: Multiplier applied to delay after each retry.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        logger.warning(
                            "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                            func.__name__, attempt + 1, max_retries, exc, current_delay,
                        )
                        time.sleep(current_delay)
                        current_delay *= backoff
            raise last_exc  # type: ignore[misc]

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            import asyncio
            current_delay = delay
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        logger.warning(
                            "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                            func.__name__, attempt + 1, max_retries, exc, current_delay,
                        )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
            raise last_exc  # type: ignore[misc]

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return wrapper

    return decorator


# --- Filename sanitization ---

_UNSAFE_CHARS = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']


def sanitize_filename(name: str) -> str:
    """Remove characters that are unsafe in file names."""
    for ch in _UNSAFE_CHARS:
        name = name.replace(ch, '_')
    return name.strip()


def sanitize_dirname(name: str, max_length: int = 100) -> str:
    """Sanitize and truncate a directory name."""
    if not name:
        return "unknown"
    return sanitize_filename(name)[:max_length]


# --- Timestamp helpers ---

def ts_to_str(ts) -> str:
    """Convert a millisecond timestamp to a human-readable string."""
    try:
        return datetime.fromtimestamp(int(ts) / 1000).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError, OSError):
        return str(ts)


# --- Download verification ---

def verify_download(file_path: str | Path) -> bool:
    """Return True if *file_path* exists and has non-zero size."""
    p = Path(file_path)
    return p.exists() and p.stat().st_size > 0


# --- State management (resume-capable downloads) ---

STATE_FILE = "download_state.json"


def load_state(output_dir: str) -> dict:
    """Load previous download state from *output_dir*."""
    state_path = os.path.join(output_dir, STATE_FILE)
    if os.path.exists(state_path):
        with open(state_path, "r") as f:
            return json.load(f)
    return {"downloaded": {}, "failed": [], "total": 0, "started_at": None}


def save_state(output_dir: str, state: dict):
    """Persist download state to *output_dir*."""
    os.makedirs(output_dir, exist_ok=True)
    state_path = os.path.join(output_dir, STATE_FILE)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
