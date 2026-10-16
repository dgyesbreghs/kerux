"""Static typing checks, verified by mypy and pyright (not collected by pytest)."""

from dataclasses import dataclass
from typing import assert_type

from kerux import Mediator, Notification, Request, SyncMediator


@dataclass
class User:
    name: str


@dataclass
class GetUser(Request[User]):
    id: int


@dataclass
class DeleteUser(Request[None]):
    id: int


@dataclass
class UserDeleted(Notification):
    id: int


async def get_user(request: GetUser) -> User:
    return User(name=str(request.id))


def delete_user(request: DeleteUser) -> None:
    pass


class GetUserHandler:
    async def handle(self, request: GetUser) -> User:
        return User(name="x")


async def check_async_mediator() -> None:
    mediator = Mediator()
    mediator.register(GetUser, get_user)
    mediator.register(DeleteUser, factory=lambda: delete_user)

    assert_type(await mediator.send(GetUser(1)), User)
    assert_type(await mediator.send(DeleteUser(1)), None)
    assert_type(await mediator.publish(UserDeleted(1)), None)


def check_sync_mediator() -> None:
    mediator = SyncMediator()
    mediator.register(DeleteUser, delete_user)

    assert_type(mediator.send(GetUser(1)), User)
    assert_type(mediator.send(DeleteUser(1)), None)


def check_registration() -> None:
    mediator = Mediator()
    mediator.register(GetUser, lambda request: User(name=str(request.id)))
    mediator.register(GetUser, GetUserHandler())
    mediator.register(GetUser, factory=GetUserHandler)
    mediator.register_notification_handler(UserDeleted, lambda notification: None)

    # A handler for a different request type is rejected.
    mediator.register(GetUser, delete_user)  # type: ignore[arg-type]


async def check_decorators() -> None:
    mediator = Mediator()

    @mediator.handler
    async def decorated(request: GetUser) -> User:
        return User(name="x")

    @mediator.handler(GetUser)
    async def explicit(request: GetUser) -> User:
        return User(name="x")

    # Decorators return the function unchanged, types included.
    assert_type(await decorated(GetUser(1)), User)
    assert_type(await explicit(GetUser(1)), User)
