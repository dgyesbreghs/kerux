import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from kerux import HandlerNotFoundError, Notification, Request, SyncMediator


@dataclass
class Echo(Request[str]):
    text: str


@dataclass
class Fire(Request[None]):
    pass


@dataclass
class Placed(Notification):
    order_id: int


def echo(request: Echo) -> str:
    return request.text


async def async_echo(request: Echo) -> str:
    return request.text


def test_send_returns_handler_response() -> None:
    mediator = SyncMediator()
    mediator.register(Echo, echo)

    assert mediator.send(Echo("hi")) == "hi"


def test_send_void_request_returns_none() -> None:
    mediator = SyncMediator()
    mediator.register(Fire, lambda request: None)

    assert mediator.send(Fire()) is None


def test_send_unregistered_request_raises_handler_not_found() -> None:
    with pytest.raises(HandlerNotFoundError):
        SyncMediator().send(Echo("hi"))


def test_behaviors_run_in_order_around_handler() -> None:
    log: list[str] = []

    def behavior(name: str) -> Callable[[Any, Callable[[], Any]], Any]:
        def wrap(request: Any, next: Callable[[], Any]) -> Any:
            log.append(f"{name} before")
            response = next()
            log.append(f"{name} after")
            return response

        return wrap

    def handler(request: Echo) -> str:
        log.append("handler")
        return request.text

    mediator = SyncMediator()
    mediator.register(Echo, handler)
    mediator.add_behavior(behavior("outer"))
    mediator.add_behavior(behavior("inner"))

    assert mediator.send(Echo("x")) == "x"
    assert log == ["outer before", "inner before", "handler", "inner after", "outer after"]


def test_short_circuiting_behavior_never_calls_factory() -> None:
    def factory() -> Callable[[Echo], str]:
        raise AssertionError("factory must not be called")

    mediator = SyncMediator()
    mediator.register(Echo, factory=factory)
    mediator.add_behavior(lambda request, next: "cached")

    assert mediator.send(Echo("x")) == "cached"


def test_publish_calls_handlers_in_registration_order() -> None:
    log: list[str] = []
    mediator = SyncMediator()
    mediator.register_notification_handler(Placed, lambda n: log.append(f"email {n.order_id}"))
    mediator.register_notification_handler(Placed, lambda n: log.append(f"audit {n.order_id}"))

    mediator.publish(Placed(3))

    assert log == ["email 3", "audit 3"]


def test_rejects_async_function_at_registration() -> None:
    with pytest.raises(TypeError, match="async"):
        SyncMediator().register(Echo, async_echo)


def test_rejects_async_function_via_decorator() -> None:
    mediator = SyncMediator()

    with pytest.raises(TypeError, match="async"):
        mediator.handler(async_echo)


def test_rejects_object_with_async_handle_at_registration() -> None:
    class EchoHandler:
        async def handle(self, request: Echo) -> str:
            return request.text

    with pytest.raises(TypeError, match="async"):
        SyncMediator().register(Echo, EchoHandler())


def test_rejects_object_with_async_call_at_registration() -> None:
    class EchoCallable:
        async def __call__(self, request: Echo) -> str:
            return request.text

    with pytest.raises(TypeError, match="async"):
        SyncMediator().register(Echo, EchoCallable())


def test_rejects_partial_of_async_function_at_registration() -> None:
    async def prefixed(prefix: str, request: Echo) -> str:
        return prefix + request.text

    with pytest.raises(TypeError, match="async"):
        SyncMediator().register(Echo, functools.partial(prefixed, ">"))


def test_rejects_async_notification_handler_at_registration() -> None:
    async def on_placed(notification: Placed) -> None: ...

    with pytest.raises(TypeError, match="async"):
        SyncMediator().register_notification_handler(Placed, on_placed)


def test_rejects_async_behavior_at_registration() -> None:
    async def behavior(request: Any, next: Callable[[], Any]) -> Any:
        return next()

    with pytest.raises(TypeError, match="async"):
        SyncMediator().add_behavior(behavior)


def test_lambda_returning_coroutine_raises_type_error_at_send() -> None:
    mediator = SyncMediator()
    mediator.register(Echo, lambda request: async_echo(request))

    # filterwarnings = error also proves the coroutine was closed, not left "never awaited".
    with pytest.raises(TypeError, match="awaitable"):
        mediator.send(Echo("x"))


def test_factory_producing_async_handler_raises_type_error_at_send() -> None:
    mediator = SyncMediator()
    mediator.register(Echo, factory=lambda: async_echo)

    with pytest.raises(TypeError, match="async"):
        mediator.send(Echo("x"))


def test_accepts_object_with_sync_handle_even_if_call_is_async() -> None:
    class Both:
        def handle(self, request: Echo) -> str:
            return "handled"

        async def __call__(self, request: Echo) -> str:
            return "called"

    mediator = SyncMediator()
    mediator.register(Echo, Both())

    assert mediator.send(Echo("x")) == "handled"


def test_mock_handler_is_called() -> None:
    from unittest.mock import Mock

    handler = Mock(return_value="mocked")
    mediator = SyncMediator()
    mediator.register(Echo, handler)

    assert mediator.send(Echo("x")) == "mocked"
    handler.assert_called_once_with(Echo("x"))
