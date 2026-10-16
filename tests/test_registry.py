import sys
from dataclasses import dataclass

import pytest

from kerux import HandlerAlreadyRegisteredError, Notification, Request
from kerux._registry import Registry

from ._future_handlers import Shout, shout


@dataclass
class GetUser(Request[str]):
    id: int


@dataclass
class UserDeleted(Notification):
    id: int


async def get_user(request: GetUser) -> str:
    return f"user {request.id}"


def test_register_requires_exactly_one_of_handler_or_factory() -> None:
    registry = Registry()

    with pytest.raises(TypeError):
        registry.register(GetUser)
    with pytest.raises(TypeError):
        registry.register(GetUser, get_user, factory=lambda: get_user)


def test_duplicate_request_handler_raises() -> None:
    registry = Registry()
    registry.register(GetUser, get_user)

    with pytest.raises(HandlerAlreadyRegisteredError):
        registry.register(GetUser, factory=lambda: get_user)


def test_handler_decorator_infers_request_type() -> None:
    registry = Registry()

    returned = registry.handler(get_user)

    assert returned is get_user
    assert registry._handlers[GetUser].resolve() is get_user


def test_handler_decorator_with_explicit_type() -> None:
    registry = Registry()

    @registry.handler(GetUser)
    def anything(request: object) -> str:
        return "x"

    assert registry._handlers[GetUser].resolve() is anything


def test_handler_decorator_resolves_future_annotations() -> None:
    registry = Registry()

    registry.handler(shout)

    assert registry._handlers[Shout].resolve() is shout


def test_handler_decorator_without_annotation_raises_type_error() -> None:
    registry = Registry()

    def unannotated(request):  # type: ignore[no-untyped-def]
        return "x"

    with pytest.raises(TypeError, match="annotation"):
        registry.handler(unannotated)


def test_handler_decorator_with_non_request_annotation_raises_type_error() -> None:
    registry = Registry()

    def wrong(request: int) -> str:
        return "x"

    with pytest.raises(TypeError, match="Request"):
        registry.handler(wrong)


def test_handler_decorator_without_parameters_raises_type_error() -> None:
    registry = Registry()

    def no_params() -> str:
        return "x"

    with pytest.raises(TypeError):
        registry.handler(no_params)


def test_notification_handler_decorator_requires_notification_subclass() -> None:
    registry = Registry()

    async def on_deleted(notification: UserDeleted) -> None: ...

    async def not_a_notification(request: GetUser) -> None: ...

    assert registry.notification_handler(on_deleted) is on_deleted
    assert registry._notification_handlers[UserDeleted][0].resolve() is on_deleted
    with pytest.raises(TypeError, match="Notification"):
        registry.notification_handler(not_a_notification)


def test_notification_handlers_allow_many_per_type() -> None:
    registry = Registry()

    async def first(notification: UserDeleted) -> None: ...

    async def second(notification: UserDeleted) -> None: ...

    registry.register_notification_handler(UserDeleted, first)
    registry.register_notification_handler(UserDeleted, factory=lambda: second)

    assert [e.resolve() for e in registry._notification_handlers[UserDeleted]] == [first, second]


def test_add_behavior_accepts_function_and_object() -> None:
    registry = Registry()

    async def logging(request: object, next: object) -> object: ...

    class Timing:
        async def handle(self, request: object, next: object) -> object: ...

    registry.add_behavior(logging)
    registry.add_behavior(Timing(), request_type=GetUser)

    assert len(registry._behaviors) == 2
    assert registry._behaviors[1].request_type is GetUser


def test_handler_decorator_ignores_unresolvable_annotations_on_other_parameters() -> None:
    from ._type_checking_handlers import Price, price

    registry = Registry()

    registry.handler(price)

    assert registry._handlers[Price].resolve() is price


@pytest.mark.skipif(sys.version_info < (3, 14), reason="deferred annotations (PEP 649) need Python 3.14")
def test_handler_decorator_with_deferred_annotations_on_314() -> None:
    namespace: dict[str, object] = {"GetUser": GetUser}
    # Without `from __future__ import annotations`, 3.14 evaluates annotations lazily; Missing is never defined.
    exec("def handler(request: GetUser, other: Missing) -> Missing: ...", namespace)
    registry = Registry()

    registry.handler(namespace["handler"])  # type: ignore[call-overload]

    assert registry._handlers[GetUser].resolve() is namespace["handler"]


def test_registering_a_handler_class_instead_of_an_instance_raises_type_error() -> None:
    class GetUserHandler:
        def handle(self, request: GetUser) -> str:
            return "x"

    with pytest.raises(TypeError, match="instance"):
        Registry().register(GetUser, GetUserHandler)  # type: ignore[arg-type]
