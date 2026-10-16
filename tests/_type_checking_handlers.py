"""A handler module that imports types only for type checkers, a common pattern with ruff's TC rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from kerux import Request

if TYPE_CHECKING:
    from decimal import Decimal


@dataclass
class Price(Request[str]):
    amount: str


async def price(request: Price, rate: Decimal | None = None) -> Decimal:
    raise NotImplementedError
