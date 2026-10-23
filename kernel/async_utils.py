"""Async plumbing every subsystem needs.

Kept dependency-free and small so any module can import it without cycles:
gather with concurrency caps, boxed timeouts that never swallow
``CancelledError``, cancellable groups, and an async-noop for optional hooks.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Iterable, TypeVar

T = TypeVar("T")


async def gather_limit(coros: Iterable[Awaitable[T]], limit: int) -> list[T]:
    """Run awaitables with at most ``limit`` in flight; preserve order."""
    semaphore = asyncio.Semaphore(max(1, limit))

    async def wrapped(coro: Awaitable[T]) -> T:
        async with semaphore:
            return await coro

    return await asyncio.gather(*(wrapped(c) for c in coros))


async def timeout_box(coro: Awaitable[T], seconds: float) -> T:
    """await ``coro`` with a timeout; re-raise TimeoutError as-is.

    Unlike ``asyncio.wait_for`` this keeps the task reference so the inner
    coroutine is always cancelled on timeout (no orphaned work).
    """
    task = asyncio.ensure_future(coro)
    try:
        return await asyncio.wait_for(asyncio.shield(task), seconds)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        raise


class TaskGroup:
    """A minimal cancellable group (pre-3.11 compatible semantics).

    ``run()`` spawns tracked tasks; ``cancel_all()`` aborts them; the async
    context manager cancels any survivors on exit and surfaces the first
    exception via ``results`` inspection instead of raising mid-shutdown.
    """

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []

    def run(self, coro: Awaitable[Any], *, name: str | None = None) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.append(task)
        return task

    def cancel_all(self) -> int:
        cancelled = 0
        for task in self._tasks:
            if not task.done():
                task.cancel()
                cancelled += 1
        return cancelled

    async def wait(self) -> list[Any]:
        return list(await asyncio.gather(*self._tasks, return_exceptions=True))

    @property
    def tasks(self) -> list[asyncio.Task]:
        return list(self._tasks)

    async def __aenter__(self) -> "TaskGroup":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        self.cancel_all()
        await self.wait()


async def maybe_await(value: Any) -> Any:
    """Await callables/results that may or may not be coroutine-like."""
    if asyncio.iscoroutine(value) or asyncio.isfuture(value):
        return await value
    if callable(value) and not isinstance(value, type):
        result = value()
        if asyncio.iscoroutine(result):
            return await result
        return result
    return value


def run_sync(coro: Awaitable[T]) -> T:
    """Run a coroutine to completion from sync code (fresh loop each call)."""
    return asyncio.run(coro)


DebounceFn = Callable[..., Awaitable[None]]


class Debouncer:
    """Coalesce bursts of calls into one trailing invocation."""

    def __init__(self, delay: float, fn: DebouncerFn):
        self.delay = delay
        self._fn = fn
        self._timer: asyncio.TimerHandle | None = None
        self._pending_args: tuple[Any, ...] = ()
        self._pending_kwargs: dict[str, Any] = {}
        self.calls = 0
        self.fired = 0

    def call(self, *args: Any, **kwargs: Any) -> None:
        self.calls += 1
        self._pending_args = args
        self._pending_kwargs = kwargs
        if self._timer is not None:
            self._timer.cancel()
        loop = asyncio.get_running_loop()
        self._timer = loop.call_later(self.delay, self._fire)

    def _fire(self) -> None:
        self.fired += 1
        asyncio.create_task(
            self._fn(*self._pending_args, **self._pending_kwargs))

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
