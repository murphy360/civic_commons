"""
Civic Commons MCP Server - Authentication

Simple API key authentication for MCP endpoints.
"""

from functools import wraps
from typing import Callable, TypeVar

from config import get_config


class AuthError(Exception):
    """Authentication error."""
    pass


def validate_api_key(api_key: str | None) -> bool:
    """
    Validate an API key against the configured key.
    
    Args:
        api_key: The API key to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not api_key:
        return False
    
    config = get_config()
    # Use constant-time comparison to prevent timing attacks
    return _constant_time_compare(api_key, config.api_key)


def _constant_time_compare(a: str, b: str) -> bool:
    """
    Compare two strings in constant time to prevent timing attacks.
    
    Args:
        a: First string
        b: Second string
        
    Returns:
        True if strings are equal, False otherwise
    """
    if len(a) != len(b):
        return False
    
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    
    return result == 0


T = TypeVar("T")


def require_auth(func: Callable[..., T]) -> Callable[..., T]:
    """
    Decorator that requires API key authentication.
    
    Expects the first argument or 'api_key' keyword argument
    to contain the API key.
    
    Raises:
        AuthError: If authentication fails
    """
    @wraps(func)
    def wrapper(*args, **kwargs) -> T:
        # Try to get API key from kwargs first
        api_key = kwargs.pop("api_key", None)
        
        if not validate_api_key(api_key):
            raise AuthError("Invalid or missing API key")
        
        return func(*args, **kwargs)
    
    return wrapper


# Rate limiting state (in production, use Redis)
_rate_limit_state: dict[str, list[float]] = {}


def check_rate_limit(client_id: str) -> bool:
    """
    Check if a client has exceeded the rate limit.
    
    Args:
        client_id: Unique identifier for the client (e.g., API key or IP)
        
    Returns:
        True if within rate limit, False if exceeded
    """
    import time
    
    config = get_config()
    now = time.time()
    window_start = now - config.rate_limit_window
    
    # Get or create request history for this client
    if client_id not in _rate_limit_state:
        _rate_limit_state[client_id] = []
    
    # Remove old requests outside the window
    _rate_limit_state[client_id] = [
        ts for ts in _rate_limit_state[client_id]
        if ts > window_start
    ]
    
    # Check if limit exceeded
    if len(_rate_limit_state[client_id]) >= config.rate_limit_requests:
        return False
    
    # Record this request
    _rate_limit_state[client_id].append(now)
    return True


class RateLimitError(Exception):
    """Rate limit exceeded error."""
    pass

