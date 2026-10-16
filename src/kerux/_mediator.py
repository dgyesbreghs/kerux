from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from ._errors import HandlerNotFoundError
from ._messages import Notification, Request
from ._registry import Registry, invoke

__all__ = ["Mediator"]

ResponseT = TypeVar("ResponseT")


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class Mediator(Registry):
    """Async mediator: sends requests to their handler and publishes notifications to all of theirs.

    Handlers and behaviors may be async or sync; a sync one runs directly on the event loop.
    """

    async def send(self, request: Request[ResponseT]) -> ResponseT:
        """Sends a request through the pipeline behaviors to its handler and returns the handler's response.

        Raises:
            HandlerNotFoundError: No handler is registered for the exact type of ``request``.
        """
        entry = self._handlers.get(type(request))
        if entry is None:
            raise HandlerNotFoundError(f"No handler registered for {type(request).__qualname__}")

        async def call_handler() -> Any:
            # Resolved only when the pipeline gets here, so a short-circuiting behavior never creates it.
            return await _await_if_needed(invoke(self._resolve(entry, "handler"), request))

        next_step: Callable[[], Awaitable[Any]] = call_handler
        for behavior in reversed(self._behaviors):
            if behavior.applies_to(request):
                next_step = self._wrap(behavior.behavior, request, next_step)

        return cast(ResponseT, await next_step())

    async def publish(self, notification: Notification) -> None:
        """Publishes a notification to every handler of its exact type, one after another in registration order.

        The first handler that raises stops the rest. Publishing without handlers does nothing.
        """
        for entry in self._notification_handlers.get(type(notification), ()):
            await _await_if_needed(invoke(self._resolve(entry, "notification handler"), notification))

    @staticmethod
    def _wrap(
        behavior: object, request: object, next_step: Callable[[], Awaitable[Any]]
    ) -> Callable[[], Awaitable[Any]]:
        async def step() -> Any:
            return await _await_if_needed(invoke(behavior, request, next_step))

        return step
