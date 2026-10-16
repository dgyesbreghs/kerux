<p align="center"><img src="https://raw.githubusercontent.com/dgyesbreghs/kerux/main/assets/icon-512.png" width="112" alt="kerux icon"></p>

# kerux

[![CI](https://github.com/dgyesbreghs/kerux/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/dgyesbreghs/kerux/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/kerux.svg)](https://pypi.org/project/kerux/)
[![Python versions](https://img.shields.io/pypi/pyversions/kerux.svg)](https://pypi.org/project/kerux/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Minimal in-process mediator for Python: requests, notifications and pipeline behaviors. Async first, fully typed.

- **Requests** with or without a response, each answered by exactly one handler
- **Notifications** published to any number of handlers
- **Pipeline behaviors** to wrap requests in logging, validation, timing, transactions, …
- **Async first**, with sync handlers welcome and a `SyncMediator` for programs without asyncio
- **Fully typed**: `await mediator.send(GetUser(id=1))` is a `User` to mypy and pyright
- No dependencies, Python 3.11+, MIT licensed

*Kerux* (κῆρυξ) is Greek for "herald". It's the Python sibling of [Herald](https://github.com/dgyesbreghs/herald) for .NET.

## Install

```bash
pip install kerux
# or
uv add kerux
```

## Getting started

```python
from dataclasses import dataclass

from kerux import Mediator, Notification, Request


@dataclass
class GetUser(Request[User]):  # answered with a User
    id: int


@dataclass
class DeleteUser(Request[None]):  # answered with nothing
    id: int


@dataclass
class UserDeleted(Notification):
    id: int


mediator = Mediator()


@mediator.handler  # the request type comes from the annotation
async def get_user(request: GetUser) -> User:
    return await users.get(request.id)


@mediator.handler
async def delete_user(request: DeleteUser) -> None:
    await users.delete(request.id)
    await mediator.publish(UserDeleted(request.id))


@mediator.notification_handler
async def send_goodbye(notification: UserDeleted) -> None: ...


user = await mediator.send(GetUser(id=1))  # User
await mediator.send(DeleteUser(id=1))  # None
```

Runnable examples live in [`examples/`](examples): a [FastAPI todo API](examples/fastapi_app.py) and a [CLI](examples/cli.py).

## Requests

A request class declares its response type: `Request[User]`, or `Request[None]` for no response. Each request type has exactly one handler, which can be:

```python
# a function, async or sync
mediator.register(GetUser, get_user)

# an object with a handle method (or any callable object)
class GetUserHandler:
    def __init__(self, users: UserRepository) -> None:
        self.users = users

    async def handle(self, request: GetUser) -> User:
        return await self.users.get(request.id)

mediator.register(GetUser, GetUserHandler(users))

# a factory, called to create the handler each time the request is sent
mediator.register(GetUser, factory=lambda: GetUserHandler(make_users()))
```

`@mediator.handler` registers a function using its first parameter's annotation; `@mediator.handler(GetUser)` names the type explicitly.

## Notifications

A notification can have any number of handlers, registered with `register_notification_handler(...)` or `@mediator.notification_handler`. `await mediator.publish(notification)` runs them one after another, in registration order.

## Pipeline behaviors

A behavior wraps every request. Call `next()` to continue to the next behavior or the handler, or return early to short-circuit:

```python
from kerux import Next


async def logging_behavior(request: object, next: Next) -> Any:
    log.info("Handling %s", type(request).__name__)
    response = await next()
    log.info("Handled %s", type(request).__name__)
    return response


mediator.add_behavior(logging_behavior)  # every request
mediator.add_behavior(validation_behavior, request_type=Validatable)  # only isinstance(request, Validatable)
```

A behavior added without `request_type` receives every request, so type checkers require it to accept any request (`request: object` or `Any`). Narrow its parameter, e.g. `request: Validatable`, only together with `request_type=Validatable`.

Behaviors run in the order added; the first one is the outermost. They also run for `Request[None]` requests, with `None` as the response. A behavior can also be an object with a `handle(request, next)` method.

## Sync programs

`SyncMediator` has the same API without `await`, for CLI tools and scripts that don't use asyncio:

```python
from kerux import SyncMediator

mediator = SyncMediator()
mediator.register(GetUser, lambda request: users.get(request.id))
user = mediator.send(GetUser(id=1))
```

Async handlers and behaviors are rejected by `SyncMediator`: at registration where possible, otherwise when called.

## FastAPI

For handlers that need request-scoped dependencies, like a database session, build a `Mediator` in a FastAPI dependency. It's cheap: a few dictionary inserts.

```python
def get_mediator(db: Annotated[Session, Depends(get_db)]) -> Mediator:
    mediator = Mediator()
    mediator.register(GetUser, factory=lambda: GetUserHandler(db))
    mediator.add_behavior(logging_behavior)
    return mediator


@app.get("/users/{user_id}")
async def read_user(user_id: int, mediator: Annotated[Mediator, Depends(get_mediator)]) -> User:
    return await mediator.send(GetUser(id=user_id))
```

FastAPI's `yield` dependencies take care of closing the session. See [`examples/fastapi_app.py`](examples/fastapi_app.py) for the full example.

## Behaviour

- Requests and notifications dispatch by **exact type**: a subclass of a registered request type is not matched.
- Sending a request without a handler raises `HandlerNotFoundError` (a `LookupError`). Registering a second handler for the same request type raises `HandlerAlreadyRegisteredError`.
- A handler factory is called only when the pipeline reaches the handler, so a short-circuiting behavior never creates it.
- Notification handlers run one after another; the first one that raises stops the rest. Publishing without handlers does nothing.
- In `Mediator`, sync handlers and behaviors run directly on the event loop. Offload long blocking work yourself, e.g. with `asyncio.to_thread`.

## Coming from Herald or MediatR

| Herald / MediatR (.NET)                        | kerux                                              |
| ---------------------------------------------- | -------------------------------------------------- |
| `IRequest<TResponse>` / `IRequest`             | `Request[T]` / `Request[None]`                     |
| `IRequestHandler<TRequest, TResponse>`         | a function or an object with `handle`              |
| `INotification` / `INotificationHandler<T>`    | `Notification` / a function or object              |
| `IPipelineBehavior<TRequest, TResponse>`       | `async def behavior(request, next)`                |
| `ISender.Send` / `IPublisher.Publish`          | `await mediator.send(...)` / `await mediator.publish(...)` |
| Assembly scanning                              | explicit `register(...)` or decorators             |

## Releasing

Publishing a GitHub release whose tag matches the version in `pyproject.toml` (e.g. `v0.2.0`) runs the `Publish` workflow, which tests, builds and uploads to PyPI via Trusted Publishing.

```bash
gh release create v0.2.0 --generate-notes
```

## License

[MIT](LICENSE)
