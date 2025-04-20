# mentis_client/__init__.py
from .client import MentisSandbox
from .exceptions import MentisSandboxError, ConnectionError, APIError, WebSocketError
# Optionally expose models if needed
# from .models import StreamMessage, CmdOutputObservationPart, ...

__all__ = [
    "MentisSandbox",
    "MentisSandboxError",
    "ConnectionError",
    "APIError",
    "WebSocketError",
    # Add model names here if they should be directly importable
]
