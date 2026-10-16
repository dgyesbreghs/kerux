# kerux: design

*2026-10-16*

## Intent

kerux is a minimal in-process mediator for Python. It is the Python sibling of [Herald](https://github.com/dgyesbreghs/herald), the .NET mediator built to replace the now commercially licensed MediatR. *Kerux* (κῆρυξ) is Greek for "herald".

It is a **public library on PyPI**. The author's own **FastAPI web API** will be its first real user, so it has to feel natural in FastAPI. It must not depend on FastAPI, though: it should work just as well in a CLI tool or any other Python program.

The model is the same as Herald's:
- send a **request** and exactly one handler answers it
- publish a **notification** and every handler for it reacts
- **pipeline behaviors** wrap requests (logging, validation, timing, transactions)

## Goals

- Requests with a response (`Request[User]`) and without one (`Request[None]`), each with exactly one handler.
- Notifications with zero or more handlers.
- Pipeline behaviors around requests.
- **Async first, with sync support.** `await mediator.send(...)` is the main API. Sync handlers also work in the async mediator, and a `SyncMediator` serves programs that don't use asyncio.
- **Fully typed.** `await mediator.send(GetUser(id=1))` is inferred as `User` by mypy and pyright, and the package ships `py.typed`.
- No runtime dependencies. Python 3.11 or newer. MIT license.

## Non-goals (version 1)

- Integrations with DI containers (`dependency-injector`, `lagom`, `svcs`, …).
- FastAPI-specific helpers. These come later, once the author's project shows what it needs. Version 1 has to be easy to use from FastAPI with plain code; see the FastAPI example.
- Streaming requests, pre/post processors, exception handlers, parallel notification publishing.
- Automatic discovery of handlers by scanning modules.

## Anti-goals

- **Magic.** No guessing whether a callable is a handler or a factory, and no hidden global registry. Registration is explicit and readable.
- **Weight.** It's a small library that a reader can understand in one sitting. If a feature needs a lot of code, it doesn't belong in version 1.
- **Lost types.** Any API shape that makes `send` return `Any` is wrong.

## API

```python
from dataclasses import dataclass
from kerux import Mediator, Notification, Request

@dataclass
class GetUser(Request[User]):
    id: int

@dataclass
class DeleteUser(Request[None]):
    id: int

@dataclass
class UserDeleted(Notification):
    id: int

mediator = Mediator()

# Handler as a plain function. The request type is inferred from the first parameter's annotation.
@mediator.handler
async def get_user(request: GetUser) -> User: ...

# Handler as an object with a `handle` method, registered explicitly.
mediator.register(DeleteUser, DeleteUserHandler(repo))

# Handler created on every send by a factory: the hook for dependencies until DI integrations exist.
mediator.register(DeleteUser, factory=lambda: DeleteUserHandler(make_repo()))

# Notification handlers: any number per notification type.
@mediator.notification_handler
async def send_goodbye(notification: UserDeleted) -> None: ...

# Behaviors, outermost first.
mediator.add_behavior(logging_behavior)
mediator.add_behavior(validation_behavior, request_type=Validatable)  # only for isinstance(request, Validatable)

user = await mediator.send(GetUser(id=1))        # -> User
await mediator.send(DeleteUser(id=1))            # -> None
await mediator.publish(UserDeleted(id=1))
```

### Requests and notifications
- `Request[R]` is a generic base class; `R` is the response type. `Request[None]` means no response. Users usually combine it with `@dataclass`, but kerux doesn't require that.
- `Notification` is a plain base class.

### Handlers
- A handler is either a callable taking the request (function, lambda, object with `__call__`) or an object with a `handle(request)` method. When both exist, `handle` is used.
- A handler may be `async` or sync.
- `register(request_type, handler)` registers a handler. `register(request_type, factory=...)` registers a zero-argument callable that creates the handler. Passing both or neither raises `TypeError`.
- The factory is called **only when the pipeline reaches the handler**, so a behavior that short-circuits never creates it. Herald 2.0 got the same fix after review.
- `@mediator.handler` infers the request type from the first parameter's annotation. `@mediator.handler(GetUser)` states it explicitly. A missing or unusable annotation raises `TypeError` at registration time.
- Requests dispatch by **exact type**. A subclass of a registered request type is not matched.
- Registering a second handler for the same request type raises `HandlerAlreadyRegisteredError`. Herald lets the first one win silently; Python favours failing loudly.
- Sending a request without a handler raises `HandlerNotFoundError` (subclass of `LookupError`).

### Notifications
- `register_notification_handler(notification_type, handler | factory=...)` and `@mediator.notification_handler` mirror the request API.
- Handlers run one after another, in registration order. The first one that raises stops the rest and the exception propagates. Publishing without handlers is a no-op.
- Notifications dispatch by **exact type**, the same as Herald.

### Behaviors
- Async mediator: `async def behavior(request, next) -> R`, where `next` is a zero-argument callable returning an awaitable of the response. A behavior may also be an object with a `handle(request, next)` method.
- Behaviors apply to every request, including `Request[None]` ones (where the response is `None`). They do not apply to notifications.
- `request_type=` limits a behavior to requests where `isinstance(request, request_type)`. This is the equivalent of Herald's constrained open behaviors.
- They run in the order added: the first added is the outermost. A behavior can short-circuit by not calling `next`.

### Sync and async
- `Mediator` is async. It calls the handler or behavior, and if the result is awaitable (`inspect.isawaitable`), awaits it. So sync and async handlers both work without kerux having to classify them up front. Sync handlers run directly on the event loop. Long blocking work should be offloaded by the user; the README says so.
- `SyncMediator` has the same API without `await`, for programs without asyncio. It rejects async handlers and behaviors in two places:
  - at registration, when detectable: `inspect.iscoroutinefunction` on the function, its `handle` method or its `__call__` method (this also sees through `functools.partial`);
  - at call time, for the rest (e.g. a lambda returning a coroutine): if a result is awaitable, it is closed and a `TypeError` is raised.
  - *(Builder's call, from the review.)*
- Both share registration logic; only dispatch differs.

### Dependencies in FastAPI (version 1)
Version 1 deliberately has no DI integration; the author wants the basics first. Factories are plain zero-argument sync callables. Request-scoped dependencies, like a per-request database session, use FastAPI's own dependency system: a FastAPI dependency builds a `Mediator` per request and registers factories that close over the session.

```python
def get_mediator(db: Session = Depends(get_db)) -> Mediator:
    mediator = Mediator()
    mediator.register(GetUser, factory=lambda: GetUserHandler(db))
    ...
    return mediator
```

Building a mediator is cheap (a few dictionary inserts), and FastAPI's `yield` dependencies take care of cleanup. The FastAPI example demonstrates this pattern next to a module-level mediator for handlers without request-scoped state. Async factories, context-manager factories and DI integrations are deferred until the author's project shows what it needs. *(Builder's call, from the review.)*

### Typing of registration
`send`/`publish` must be strictly typed (see the anti-goals). For registration, type checkers verify that the handler accepts the registered request type. They do not verify that its return type matches the request's response type: Python's type system can't link the two without heavy overloads, and that would fight the "small" anti-goal. *(Builder's call, from the review.)*

## Constraints

- Python 3.11+. Use `typing.Generic`/`TypeVar` rather than PEP 695 syntax, which needs 3.12.
- Zero runtime dependencies.
- Type-checks cleanly under `mypy --strict` and pyright (strict). A typing test confirms that `send` infers the response type.
- Modern packaging: `pyproject.toml`, src layout, `py.typed`.

## Repository and release

- A GitHub repo named `kerux`, laid out like Herald: README with badges (CI, PyPI version, Python versions, license), MIT `LICENSE`, `examples/`.
- CI on push and PR: ruff (lint and format check), mypy and pyright, and pytest on Python 3.11–3.14.
- The repository is `github.com/dgyesbreghs/kerux`; the author created it.
- Publishing a GitHub release builds the package and uploads it to PyPI via **Trusted Publishing**, the same as Herald on NuGet. The workflow runs in a GitHub environment named `pypi`. The author sets up a "pending publisher" for `kerux` on their PyPI account.
- The first release is **0.1.0**, so the API can still change after it has been used in the author's FastAPI project. *(Builder's call, from the review.)*
- Examples, which are not part of the package:
  - `examples/fastapi_app.py`: a small todo API using requests, a void request, a notification and a behavior. FastAPI is an example-only dependency.
  - `examples/cli.py`: the same idea with `SyncMediator`.

## Left to the builder

- Internal structure and module layout.
- Exact exception hierarchy beyond the names above (a common `KeruxError` base is fine).
- Test layout. Tests use pytest; async tests use whatever is lightest (`anyio` or `pytest-asyncio`).
- Build backend and tooling (`uv`, `hatchling`, …).
