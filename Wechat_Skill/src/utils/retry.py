"""Retry decorator with exponential backoff.

Usage:
    from src.utils.retry import retry

    @retry(max_attempts=3, backoff=1.0)
    async def flaky_operation():
        ...
"""
from __future__ import annotations

import asyncio
import functools
import time
from typing import Callable, Type, Tuple


def retry(
    max_attempts: int = 3,
    backoff: float = 1.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Callable | None = None,
):
    """Retry decorator for async functions.

    Args:
        max_attempts: maximum number of attempts (including first)
        backoff: base backoff in seconds; actual wait = backoff * (2 ** (attempt-1))
        exceptions: exception types that should trigger retry
        on_retry: optional callback(attempt, exception) called before each retry

    Returns:
        Decorated async function.

    Example:
        @retry(max_attempts=3, backoff=0.5)
        async def find_element():
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        wait = backoff * (2 ** (attempt - 1))
                        if on_retry:
                            on_retry(attempt, e)
                        await asyncio.sleep(wait)
            raise last_exception
        return wrapper
    return decorator


def retry_sync(
    max_attempts: int = 3,
    backoff: float = 1.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """Retry decorator for synchronous functions (used by RpaController methods)."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        time.sleep(backoff * (2 ** (attempt - 1)))
            raise last_exception
        return wrapper
    return decorator
