from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest

from kerux import HandlerNotFoundError, Mediator, Notification, Request


@dataclass
class Echo(Request[str]):
    text: str


@dataclass
class SpecialEcho(Echo):
    pass


@dataclass
class Fire(Request[None]):
    pass


@dataclass
class Audited(Request[str]):
    pass


@dataclass
class Placed(Notification):
    order_id: int


class Log:
    def __init__(self) -> None:
        self.entries: list[str] = []


async def echo(request: Echo) -> str:
    return request.text


async def test_send_with_async_function_handler() -> None:
    mediator = Mediator()
    mediator.register(Echo, echo)

    assert await mediator.send(Echo("hi")) == "hi"


async def test_send_with_sync_function_handler() -> None:
    mediator = Mediator()
    mediator.register(Echo, lambda request: request.text.upper())

    assert await mediator.send(Echo("hi")) == "HI"


async def test_send_with_object_with_async_handle() -> None:
    class EchoHandler:
        async def handle(self, request: Echo) -> str:
            return f"handled {request.text}"

    mediator = Mediator()
    mediator.register(Echo, EchoHandler())

    assert await mediator.send(Echo("hi")) == "handled hi"


async def test_send_with_callable_object() -> None:
    class EchoCallable:
        def __call__(self, request: Echo) -> str:
            return f"called {request.text}"

    mediator = Mediator()
    mediator.register(Echo, EchoCallable())

    assert await mediator.send(Echo("hi")) == "called hi"


async def test_send_void_request_returns_none() -> None:
    log = Log()
    mediator = Mediator()

    async def fire(request: Fire) -> None:
        log.entries.append("fire")

    mediator.register(Fire, fire)

    assert await mediator.send(Fire()) is None
    assert log.entries == ["fire"]


async def test_factory_is_called_once_per_send() -> None:
    created: list[int] = []

    def factory() -> Callable[[Echo], Awaitable[str]]:
        created.append(1)
        return echo

    mediator = Mediator()
    mediator.register(Echo, factory=factory)

    await mediator.send(Echo("a"))
    await mediator.send(Echo("b"))

    assert len(created) == 2


async def test_send_unregistered_request_raises_handler_not_found() -> None:
    with pytest.raises(HandlerNotFoundError):
        await Mediator().send(Echo("hi"))


async def test_send_subclass_of_registered_request_raises_handler_not_found() -> None:
    mediator = Mediator()
    mediator.register(Echo, echo)

    with pytest.raises(HandlerNotFoundError):
        await mediator.send(SpecialEcho("hi"))


def recording_behavior(log: Log, name: str) -> Callable[[Any, Callable[[], Any]], Awaitable[Any]]:
    async def behavior(request: Any, next: Callable[[], Any]) -> Any:
        log.entries.append(f"{name} before")
        response = await next()
        log.entries.append(f"{name} after")
        return response

    return behavior


async def test_behaviors_run_in_order_around_handler() -> None:
    log = Log()
    mediator = Mediator()

    async def handler(request: Echo) -> str:
        log.entries.append("handler")
        return request.text

    mediator.register(Echo, handler)
    mediator.add_behavior(recording_behavior(log, "outer"))
    mediator.add_behavior(recording_behavior(log, "inner"))

    assert await mediator.send(Echo("x")) == "x"
    assert log.entries == ["outer before", "inner before", "handler", "inner after", "outer after"]


async def test_sync_behavior_works_in_async_mediator() -> None:
    mediator = Mediator()
    mediator.register(Echo, echo)
    mediator.add_behavior(lambda request, next: next())

    assert await mediator.send(Echo("x")) == "x"


async def test_object_behavior_with_handle() -> None:
    class Upper:
        async def handle(self, request: Any, next: Callable[[], Any]) -> Any:
            return (await next()).upper()

    mediator = Mediator()
    mediator.register(Echo, echo)
    mediator.add_behavior(Upper())

    assert await mediator.send(Echo("x")) == "X"


async def test_behavior_with_request_type_is_skipped_for_other_requests() -> None:
    log = Log()
    mediator = Mediator()
    mediator.register(Echo, echo)
    mediator.register(Audited, lambda request: "audited")
    mediator.add_behavior(recording_behavior(log, "audit"), request_type=Audited)

    await mediator.send(Echo("x"))
    assert log.entries == []

    await mediator.send(Audited())
    assert log.entries == ["audit before", "audit after"]


async def test_short_circuiting_behavior_never_calls_factory() -> None:
    def factory() -> Callable[[Echo], str]:
        raise AssertionError("factory must not be called")

    async def cached(request: Any, next: Callable[[], Any]) -> Any:
        return "cached"

    mediator = Mediator()
    mediator.register(Echo, factory=factory)
    mediator.add_behavior(cached)

    assert await mediator.send(Echo("x")) == "cached"


async def test_handler_exception_propagates_through_behaviors_unchanged() -> None:
    error = ValueError("boom")

    async def failing(request: Echo) -> str:
        raise error

    mediator = Mediator()
    mediator.register(Echo, failing)
    mediator.add_behavior(recording_behavior(Log(), "outer"))

    with pytest.raises(ValueError) as caught:
        await mediator.send(Echo("x"))
    assert caught.value is error


async def test_behaviors_apply_to_void_requests() -> None:
    log = Log()
    mediator = Mediator()
    mediator.register(Fire, lambda request: None)
    mediator.add_behavior(recording_behavior(log, "outer"))

    assert await mediator.send(Fire()) is None
    assert log.entries == ["outer before", "outer after"]


async def test_publish_calls_handlers_in_registration_order() -> None:
    log = Log()
    mediator = Mediator()

    async def email(notification: Placed) -> None:
        log.entries.append(f"email {notification.order_id}")

    def audit(notification: Placed) -> None:
        log.entries.append(f"audit {notification.order_id}")

    mediator.register_notification_handler(Placed, email)
    mediator.register_notification_handler(Placed, audit)

    await mediator.publish(Placed(7))

    assert log.entries == ["email 7", "audit 7"]


async def test_publish_without_handlers_does_nothing() -> None:
    await Mediator().publish(Placed(1))


async def test_publish_stops_at_first_failing_handler() -> None:
    log = Log()
    mediator = Mediator()

    def explode(notification: Placed) -> None:
        log.entries.append("explode")
        raise RuntimeError("boom")

    mediator.register_notification_handler(Placed, explode)
    mediator.register_notification_handler(Placed, lambda notification: log.entries.append("never"))

    with pytest.raises(RuntimeError):
        await mediator.publish(Placed(1))
    assert log.entries == ["explode"]


async def test_publish_resolves_notification_factories_lazily() -> None:
    log = Log()
    mediator = Mediator()

    def factory() -> Callable[[Placed], None]:
        log.entries.append("created")
        return lambda notification: log.entries.append("handled")

    mediator.register_notification_handler(Placed, factory=factory)
    assert log.entries == []

    await mediator.publish(Placed(1))
    assert log.entries == ["created", "handled"]


async def test_decorated_handlers_are_dispatched() -> None:
    mediator = Mediator()

    @mediator.handler
    async def handle_echo(request: Echo) -> str:
        return request.text * 2

    assert await mediator.send(Echo("ab")) == "abab"


async def test_async_mock_handler_is_called() -> None:
    from unittest.mock import AsyncMock

    handler = AsyncMock(return_value="mocked")
    mediator = Mediator()
    mediator.register(Echo, handler)

    assert await mediator.send(Echo("x")) == "mocked"
    handler.assert_awaited_once_with(Echo("x"))
