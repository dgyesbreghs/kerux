__all__ = ["HandlerAlreadyRegisteredError", "HandlerNotFoundError", "KeruxError"]


class KeruxError(Exception):
    """Base class for all kerux errors."""


class HandlerNotFoundError(KeruxError, LookupError):
    """Raised when a request is sent that has no registered handler."""


class HandlerAlreadyRegisteredError(KeruxError, ValueError):
    """Raised when a second handler is registered for the same request type."""
