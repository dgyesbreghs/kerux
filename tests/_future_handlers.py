"""Handlers defined with postponed (string) annotations."""

from __future__ import annotations

from dataclasses import dataclass

from kerux import Request


@dataclass
class Shout(Request[str]):
    text: str


async def shout(request: Shout) -> str:
    return request.text.upper()
