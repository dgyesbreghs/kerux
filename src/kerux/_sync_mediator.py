from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar, cast

from ._errors import HandlerNotFoundError
from ._messages import Notification, Request
from ._registry import Registry, handle_method, invoke

__all__ = ["SyncMediator"]

ResponseT = TypeVar("ResponseT")


def _is_async(target: object) -> bool:
    """Whether what kerux would call on the target (its ``handle`` method, otherwise itself) is a coroutine function."""
    handle = handle_method(target)
    if handle is not None:
        return inspect.iscoroutinefunction(handle)
    call = getattr(target, "__call__", None)  # noqa: B004
    return inspect.iscoroutinefunction(target) or inspect.iscoroutinefunction(call)


def _ensure_sync_result(value: Any, target: object) -> Any:
    if inspect.isawaitable(value):
        if inspect.iscoroutine(value):
            value.close()
        raise TypeError(
            f"{target!r} returned an awaitable, which SyncMediator cannot await; use Mediator for async handlers"
        )
    return value


class SyncMediator(Registry):
    """Sync mediator for programs without asyncio: the same API as :class:`Mediator`, without ``await``.

    Async handlers and behaviors are rejected: at registration when detectable, otherwise when called.
    """

    def send(self, request: Request[ResponseT]) -> ResponseT:
        """Sends a request through the pipeline behaviors to its handler and returns the handler's response.

        Raises:
            HandlerNotFoundError: No handler is registered for the exact type of ``request``.
            TypeError: The handler or a behavior turned out to be async.
        """
        entry = self._handlers.get(type(request))
        if entry is None:
            raise HandlerNotFoundError(f"No handler registered for {type(request).__qualname__}")

        def call_handler() -> Any:
            # Resolved only when the pipeline gets here, so a short-circuiting behavior never creates it.
            handler = self._resolve(entry, "handler")
            return _ensure_sync_result(invoke(handler, request), handler)

        next_step: Callable[[], Any] = call_handler
        for behavior in reversed(self._behaviors):
            if behavior.applies_to(request):
                next_step = self._wrap(behavior.behavior, request, next_step)

        return cast(ResponseT, next_step())

    def publish(self, notification: Notification) -> None:
        """Publishes a notification to every handler of its exact type, one after another in registration order.

        The first handler that raises stops the rest. Publishing without handlers does nothing.
        """
        for entry in self._notification_handlers.get(type(notification), ()):
            handler = self._resolve(entry, "notification handler")
            _ensure_sync_result(invoke(handler, notification), handler)

    def _validate(self, target: object, kind: str) -> None:
        if _is_async(target):
            raise TypeError(
                f"The {kind} {target!r} is async; SyncMediator only runs sync handlers and behaviors, use Mediator"
            )

    @staticmethod
    def _wrap(behavior: object, request: object, next_step: Callable[[], Any]) -> Callable[[], Any]:
        def step() -> Any:
            return _ensure_sync_result(invoke(behavior, request, next_step), behavior)

        return step
