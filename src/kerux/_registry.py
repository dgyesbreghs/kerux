from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias, TypeVar, overload

from ._errors import HandlerAlreadyRegisteredError
from ._messages import Notification, Request

__all__ = ["Registry"]

MessageT = TypeVar("MessageT")
MessageT_contra = TypeVar("MessageT_contra", contravariant=True)
RequestT = TypeVar("RequestT", bound=Request[Any])
NotificationT = TypeVar("NotificationT", bound=Notification)
FuncT = TypeVar("FuncT", bound=Callable[..., Any])


class SupportsHandle(Protocol[MessageT_contra]):
    """An object handling a request or notification through its ``handle`` method."""

    def handle(self, message: MessageT_contra, /) -> Any: ...


HandlerLike: TypeAlias = "Callable[[MessageT], Any] | SupportsHandle[MessageT]"
"""A callable taking the message, or an object with a ``handle(message)`` method."""

Next: TypeAlias = Callable[[], Any]
"""Continues the pipeline: calls the next behavior, or the handler itself."""


class SupportsBehavior(Protocol):
    """An object wrapping requests through its ``handle(request, next)`` method."""

    def handle(self, request: Any, next: Next, /) -> Any: ...


BehaviorLike: TypeAlias = "Callable[[Any, Next], Any] | SupportsBehavior"
"""A callable taking ``(request, next)``, or an object with a ``handle(request, next)`` method."""


@dataclass(frozen=True, slots=True)
class _HandlerEntry:
    handler: object | None
    factory: Callable[[], object] | None

    def resolve(self) -> object:
        """Returns the handler, creating it with the factory if one was registered."""
        return self.factory() if self.factory is not None else self.handler


@dataclass(frozen=True, slots=True)
class _BehaviorEntry:
    behavior: object
    request_type: type | None

    def applies_to(self, request: object) -> bool:
        return self.request_type is None or isinstance(request, self.request_type)


def _invoke(target: object, *args: object) -> Any:
    """Calls ``target.handle(*args)`` if it has a ``handle`` method, otherwise ``target(*args)``."""
    handle = getattr(target, "handle", None)
    if callable(handle):
        return handle(*args)
    if callable(target):
        return target(*args)
    raise TypeError(f"{target!r} is not callable and has no handle method")


def _entry(handler: object | None, factory: Callable[[], object] | None) -> _HandlerEntry:
    if (handler is None) == (factory is None):
        raise TypeError("Pass exactly one of a handler or factory=...")
    return _HandlerEntry(handler, factory)


def _infer_message_type(func: Callable[..., Any], base: type, kind: str) -> type:
    """Reads the message type from the annotation of the function's first parameter."""
    name = getattr(func, "__qualname__", repr(func))
    try:
        parameters = list(inspect.signature(func).parameters.values())
    except (TypeError, ValueError) as error:
        raise TypeError(f"Cannot inspect the signature of {name}") from error
    if not parameters:
        raise TypeError(f"{name} must take the {kind} as its first parameter")

    try:
        hints = typing.get_type_hints(func)
    except NameError as error:
        raise TypeError(f"Cannot resolve the type annotations of {name}: {error}") from error

    annotation = hints.get(parameters[0].name)
    if annotation is None:
        raise TypeError(
            f"The first parameter of {name} has no type annotation; annotate it with the {kind} type "
            f"or pass the type explicitly"
        )
    if not (isinstance(annotation, type) and issubclass(annotation, base)):
        raise TypeError(f"The first parameter of {name} must be annotated with a {base.__name__} subclass")
    return annotation


class Registry:
    """Holds request handlers, notification handlers and pipeline behaviors."""

    def __init__(self) -> None:
        self._handlers: dict[type, _HandlerEntry] = {}
        self._notification_handlers: dict[type, list[_HandlerEntry]] = {}
        self._behaviors: list[_BehaviorEntry] = []

    @overload
    def register(self, request_type: type[RequestT], handler: HandlerLike[RequestT], /) -> None: ...

    @overload
    def register(self, request_type: type[RequestT], /, *, factory: Callable[[], HandlerLike[RequestT]]) -> None: ...

    def register(
        self,
        request_type: type[RequestT],
        handler: HandlerLike[RequestT] | None = None,
        /,
        *,
        factory: Callable[[], HandlerLike[RequestT]] | None = None,
    ) -> None:
        """Registers the handler for a request type: a ready handler, or a ``factory`` creating one per request.

        Raises:
            TypeError: Neither or both of ``handler`` and ``factory`` were passed.
            HandlerAlreadyRegisteredError: The request type already has a handler.
        """
        entry = _entry(handler, factory)
        if request_type in self._handlers:
            raise HandlerAlreadyRegisteredError(f"{request_type.__qualname__} already has a handler")
        if handler is not None:
            self._validate(handler, "handler")
        self._handlers[request_type] = entry

    @overload
    def handler(self, request_type: type[Request[Any]], /) -> Callable[[FuncT], FuncT]: ...

    @overload
    def handler(self, func: FuncT, /) -> FuncT: ...

    def handler(self, target: Any, /) -> Any:
        """Decorator registering a function as a request handler.

        ``@mediator.handler`` infers the request type from the first parameter's annotation;
        ``@mediator.handler(GetUser)`` names it explicitly. The function is returned unchanged.
        """
        if isinstance(target, type):
            request_type: type = target

            def decorator(func: FuncT) -> FuncT:
                self.register(request_type, func)
                return func

            return decorator

        self.register(_infer_message_type(target, Request, "request"), target)
        return target

    @overload
    def register_notification_handler(
        self, notification_type: type[NotificationT], handler: HandlerLike[NotificationT], /
    ) -> None: ...

    @overload
    def register_notification_handler(
        self, notification_type: type[NotificationT], /, *, factory: Callable[[], HandlerLike[NotificationT]]
    ) -> None: ...

    def register_notification_handler(
        self,
        notification_type: type[NotificationT],
        handler: HandlerLike[NotificationT] | None = None,
        /,
        *,
        factory: Callable[[], HandlerLike[NotificationT]] | None = None,
    ) -> None:
        """Adds a handler for a notification type. A notification type can have any number of handlers.

        Raises:
            TypeError: Neither or both of ``handler`` and ``factory`` were passed.
        """
        entry = _entry(handler, factory)
        if handler is not None:
            self._validate(handler, "notification handler")
        self._notification_handlers.setdefault(notification_type, []).append(entry)

    @overload
    def notification_handler(self, notification_type: type[Notification], /) -> Callable[[FuncT], FuncT]: ...

    @overload
    def notification_handler(self, func: FuncT, /) -> FuncT: ...

    def notification_handler(self, target: Any, /) -> Any:
        """Decorator registering a function as a notification handler; see :meth:`handler`."""
        if isinstance(target, type):
            notification_type: type = target

            def decorator(func: FuncT) -> FuncT:
                self.register_notification_handler(notification_type, func)
                return func

            return decorator

        self.register_notification_handler(_infer_message_type(target, Notification, "notification"), target)
        return target

    def add_behavior(self, behavior: BehaviorLike, /, *, request_type: type | None = None) -> None:
        """Adds a pipeline behavior. Behaviors run in the order added: the first added is the outermost.

        Args:
            behavior: A callable taking ``(request, next)``, or an object with a ``handle(request, next)`` method.
            request_type: Only run the behavior for requests where ``isinstance(request, request_type)``.
        """
        self._validate(behavior, "behavior")
        self._behaviors.append(_BehaviorEntry(behavior, request_type))

    def _validate(self, target: object, kind: str) -> None:
        """Hook for subclasses to reject handlers or behaviors they cannot run."""

    def _resolve(self, entry: _HandlerEntry, kind: str) -> object:
        """Resolves an entry, validating handlers created by a factory."""
        target = entry.resolve()
        if entry.factory is not None:
            self._validate(target, kind)
        return target
