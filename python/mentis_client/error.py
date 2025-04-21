# mentis_client/error.py
from typing import Optional, Any, Dict

class MentisError(Exception):
    """Base exception class for all Mentis client errors"""
    
    def __init__(self, message: str, **kwargs):
        self.message = message
        self.details = kwargs
        super().__init__(message)
        
    def __str__(self) -> str:
        details = ", ".join(f"{k}={v}" for k, v in self.details.items())
        if details:
            return f"{self.message} ({details})"
        return self.message


class MentisAPIError(MentisError):
    """Exception raised when API requests fail"""
    
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_detail: Optional[str] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.status_code = status_code
        self.error_detail = error_detail


class MentisValidationError(MentisError):
    """Exception raised when validation fails"""
    
    def __init__(self, message: str, validation_errors: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.validation_errors = validation_errors or {}


class MentisConnectionError(MentisError):
    """Exception raised when connection to the server fails"""
    
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.original_error = original_error


class MentisTimeoutError(MentisError):
    """Exception raised when a request times out"""
    
    def __init__(self, message: str, timeout: Optional[float] = None):
        super().__init__(message)
        self.timeout = timeout


class MentisResourceError(MentisError):
    """Exception raised when resource operations fail"""
    
    def __init__(
        self,
        message: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        **kwargs
    ):
        super().__init__(message, **kwargs)
        self.resource_type = resource_type
        self.resource_id = resource_id 