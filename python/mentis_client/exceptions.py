# mentis_client/exceptions.py

class MentisSandboxError(Exception):
    """Base exception for mentis_client errors."""
    pass

class ConnectionError(MentisSandboxError):
    """Raised for issues connecting to the MentisRuntime service."""
    pass

class APIError(MentisSandboxError):
    """Error returned by the API."""
    def __init__(self, message, status_code: int | None = None, action_id: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.action_id = action_id  # 保留参数以兼容现有代码，但不再主动设置

    def __str__(self):
        s = super().__str__()
        if self.status_code:
            s = f"{s} (HTTP {self.status_code})"
        if self.action_id:
            s = f"{s} (ActionID: {self.action_id})"
        return s

class WebSocketError(MentisSandboxError):
    """Raised for issues related to the WebSocket connection or stream."""
    pass
