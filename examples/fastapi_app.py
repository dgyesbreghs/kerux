"""A small todo API showing kerux in FastAPI.

Run it with:  uv run fastapi dev examples/fastapi_app.py

It shows:
- a query (`ListTodos`), a command with a response (`CreateTodo`) and one without (`CompleteTodo`)
- a notification (`TodoCompleted`) with two handlers
- a logging behavior for every request, and a validation behavior only for `Validatable` requests
- the request-scoped pattern: a FastAPI dependency builds a `Mediator` per request whose handlers
  share that request's repository (think: database session)
"""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, replace
from typing import Annotated, Any

from fastapi import Depends, FastAPI, status
from fastapi import Request as HttpRequest
from fastapi.responses import JSONResponse

from kerux import Mediator, Notification, Request

logger = logging.getLogger("todos")


# --- Domain -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Todo:
    id: uuid.UUID
    title: str
    completed: bool = False


class TodoNotFoundError(LookupError):
    pass


class ValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__(" ".join(errors))
        self.errors = errors


class TodoRepository:
    """Stands in for a database session: created per request, closed when the request ends."""

    def __init__(self, rows: dict[uuid.UUID, Todo]) -> None:
        self._rows = rows

    def all(self) -> list[Todo]:
        return sorted(self._rows.values(), key=lambda todo: todo.title)

    def get(self, todo_id: uuid.UUID) -> Todo:
        try:
            return self._rows[todo_id]
        except KeyError:
            raise TodoNotFoundError(f"Todo {todo_id} not found") from None

    def save(self, todo: Todo) -> None:
        self._rows[todo.id] = todo

    def close(self) -> None:
        pass


@dataclass
class Statistics:
    completed: int = 0


# --- Requests and notifications ---------------------------------------------------------------------------


class Validatable:
    def validate(self) -> list[str]:
        return []


@dataclass
class ListTodos(Request[list[Todo]]):
    pass


@dataclass
class CreateTodo(Request[Todo], Validatable):
    title: str

    def validate(self) -> list[str]:
        if not self.title.strip():
            return ["Title is required."]
        if len(self.title) > 100:
            return ["Title must be 100 characters or fewer."]
        return []


@dataclass
class CompleteTodo(Request[None]):
    todo_id: uuid.UUID


@dataclass
class TodoCompleted(Notification):
    todo_id: uuid.UUID
    title: str


# --- Handlers ---------------------------------------------------------------------------------------------


class ListTodosHandler:
    def __init__(self, repository: TodoRepository) -> None:
        self.repository = repository

    def handle(self, request: ListTodos) -> list[Todo]:
        return self.repository.all()


class CreateTodoHandler:
    def __init__(self, repository: TodoRepository) -> None:
        self.repository = repository

    async def handle(self, request: CreateTodo) -> Todo:
        todo = Todo(id=uuid.uuid4(), title=request.title.strip())
        self.repository.save(todo)
        return todo


class CompleteTodoHandler:
    def __init__(self, repository: TodoRepository, mediator: Mediator) -> None:
        self.repository = repository
        self.mediator = mediator

    async def handle(self, request: CompleteTodo) -> None:
        todo = self.repository.get(request.todo_id)
        if todo.completed:
            return
        self.repository.save(replace(todo, completed=True))
        await self.mediator.publish(TodoCompleted(todo.id, todo.title))


async def log_completed(notification: TodoCompleted) -> None:
    logger.info("Todo %r was completed", notification.title)


# --- Behaviors --------------------------------------------------------------------------------------------


async def logging_behavior(request: Any, next: Callable[[], Awaitable[Any]]) -> Any:
    started = time.perf_counter()
    response = await next()
    logger.info("Handled %s in %.1f ms", type(request).__name__, (time.perf_counter() - started) * 1000)
    return response


async def validation_behavior(request: Validatable, next: Callable[[], Awaitable[Any]]) -> Any:
    if errors := request.validate():
        raise ValidationError(errors)
    return await next()


# --- Application ------------------------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(title="kerux todos")
    rows: dict[uuid.UUID, Todo] = {}
    statistics = Statistics()

    def get_repository() -> Iterator[TodoRepository]:
        repository = TodoRepository(rows)
        try:
            yield repository
        finally:
            repository.close()

    def get_mediator(repository: Annotated[TodoRepository, Depends(get_repository)]) -> Mediator:
        # Built per request so handlers share this request's repository. Building one is a few dict inserts.
        mediator = Mediator()
        mediator.register(ListTodos, factory=lambda: ListTodosHandler(repository))
        mediator.register(CreateTodo, factory=lambda: CreateTodoHandler(repository))
        mediator.register(CompleteTodo, factory=lambda: CompleteTodoHandler(repository, mediator))

        mediator.register_notification_handler(TodoCompleted, log_completed)

        @mediator.notification_handler
        def count_completed(notification: TodoCompleted) -> None:
            statistics.completed += 1

        mediator.add_behavior(logging_behavior)
        mediator.add_behavior(validation_behavior, request_type=Validatable)
        return mediator

    @app.exception_handler(ValidationError)
    async def on_validation_error(request: HttpRequest, error: ValidationError) -> JSONResponse:
        return JSONResponse({"detail": error.errors}, status_code=status.HTTP_400_BAD_REQUEST)

    @app.exception_handler(TodoNotFoundError)
    async def on_not_found(request: HttpRequest, error: TodoNotFoundError) -> JSONResponse:
        return JSONResponse({"detail": str(error)}, status_code=status.HTTP_404_NOT_FOUND)

    @app.get("/todos")
    async def list_todos(mediator: Annotated[Mediator, Depends(get_mediator)]) -> list[Todo]:
        return await mediator.send(ListTodos())

    @app.post("/todos", status_code=status.HTTP_201_CREATED)
    async def create_todo(command: CreateTodo, mediator: Annotated[Mediator, Depends(get_mediator)]) -> Todo:
        return await mediator.send(command)

    @app.post("/todos/{todo_id}/complete", status_code=status.HTTP_204_NO_CONTENT)
    async def complete_todo(todo_id: uuid.UUID, mediator: Annotated[Mediator, Depends(get_mediator)]) -> None:
        await mediator.send(CompleteTodo(todo_id))

    @app.get("/stats")
    async def stats() -> dict[str, int]:
        return {"completed": statistics.completed}

    return app


app = create_app()
