"""A small todo CLI showing kerux without asyncio, using SyncMediator.

python examples/cli.py add "Try kerux"
python examples/cli.py list
python examples/cli.py done 1
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from kerux import Notification, Request, SyncMediator


@dataclass
class Todo:
    id: int
    title: str
    completed: bool = False


class TodoFile:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[Todo]:
        if not self.path.exists():
            return []
        return [Todo(**row) for row in json.loads(self.path.read_text())]

    def save(self, todos: list[Todo]) -> None:
        self.path.write_text(json.dumps([asdict(todo) for todo in todos], indent=2))


class UserError(Exception):
    pass


@dataclass
class AddTodo(Request[Todo]):
    title: str


@dataclass
class ListTodos(Request[list[Todo]]):
    pass


@dataclass
class CompleteTodo(Request[None]):
    todo_id: int


@dataclass
class TodoCompleted(Notification):
    todo: Todo


def build_mediator(store: TodoFile) -> SyncMediator:
    mediator = SyncMediator()

    @mediator.handler
    def add(request: AddTodo) -> Todo:
        todos = store.load()
        todo = Todo(id=max((t.id for t in todos), default=0) + 1, title=request.title)
        store.save([*todos, todo])
        return todo

    @mediator.handler
    def list_todos(request: ListTodos) -> list[Todo]:
        return store.load()

    @mediator.handler
    def complete(request: CompleteTodo) -> None:
        todos = store.load()
        todo = next((t for t in todos if t.id == request.todo_id), None)
        if todo is None:
            raise UserError(f"#{request.todo_id} not found")
        todo.completed = True
        store.save(todos)
        mediator.publish(TodoCompleted(todo))

    @mediator.notification_handler
    def announce(notification: TodoCompleted) -> None:
        print(f"Completed #{notification.todo.id}: {notification.todo.title}")

    def validate_title(request: AddTodo, next: Callable[[], Any]) -> Any:
        if not request.title.strip():
            raise UserError("Title is required.")
        return next()

    mediator.add_behavior(validate_title, request_type=AddTodo)
    return mediator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A tiny todo list built on kerux.")
    parser.add_argument("--file", type=Path, default=Path("todos.json"), help="where todos are stored")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("add", help="add a todo").add_argument("title")
    commands.add_parser("list", help="list todos")
    commands.add_parser("done", help="complete a todo").add_argument("id", type=int)
    args = parser.parse_args(argv)

    mediator = build_mediator(TodoFile(args.file))
    try:
        if args.command == "add":
            todo = mediator.send(AddTodo(args.title))
            print(f"Added #{todo.id}: {todo.title}")
        elif args.command == "list":
            for todo in mediator.send(ListTodos()):
                print(f"[{'x' if todo.completed else ' '}] #{todo.id} {todo.title}")
        else:
            mediator.send(CompleteTodo(args.id))
    except UserError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
