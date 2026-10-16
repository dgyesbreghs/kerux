"""Smoke tests for the runnable examples in ``examples/``."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def load_example(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"examples.{name}", EXAMPLES / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses with postponed annotations look their module up here
    spec.loader.exec_module(module)
    return module


def test_fastapi_example() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    client = TestClient(load_example("fastapi_app").create_app())

    created = client.post("/todos", json={"title": "Try kerux"})
    assert created.status_code == 201
    todo = created.json()
    assert todo["title"] == "Try kerux"
    assert todo["completed"] is False

    invalid = client.post("/todos", json={"title": "  "})
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == ["Title is required."]

    assert [t["title"] for t in client.get("/todos").json()] == ["Try kerux"]

    assert client.post(f"/todos/{todo['id']}/complete").status_code == 204
    assert client.get("/todos").json()[0]["completed"] is True
    assert client.get("/stats").json() == {"completed": 1}

    missing = client.post("/todos/00000000-0000-0000-0000-000000000000/complete")
    assert missing.status_code == 404


def run_cli(*args: str, file: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(EXAMPLES / "cli.py"), "--file", str(file), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_example(tmp_path: Path) -> None:
    file = tmp_path / "todos.json"

    added = run_cli("add", "Try kerux", file=file)
    assert added.returncode == 0, added.stderr
    assert added.stdout.strip() == "Added #1: Try kerux"

    assert run_cli("list", file=file).stdout.strip() == "[ ] #1 Try kerux"

    done = run_cli("done", "1", file=file)
    assert done.returncode == 0, done.stderr
    assert "Completed #1: Try kerux" in done.stdout

    assert run_cli("list", file=file).stdout.strip() == "[x] #1 Try kerux"

    invalid = run_cli("add", "", file=file)
    assert invalid.returncode == 1
    assert "Title is required." in invalid.stderr

    missing = run_cli("done", "42", file=file)
    assert missing.returncode == 1
    assert "#42 not found" in missing.stderr
