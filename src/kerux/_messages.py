from typing import Generic, TypeVar

__all__ = ["Notification", "Request"]

ResponseT_co = TypeVar("ResponseT_co", covariant=True)


class Request(Generic[ResponseT_co]):
    """Base class for a request answered by exactly one handler.

    The type argument is the response type: ``class GetUser(Request[User])`` is answered with a ``User``,
    ``class DeleteUser(Request[None])`` with nothing.
    """

    __slots__ = ()


class Notification:
    """Base class for a notification published to zero or more handlers."""

    __slots__ = ()
