"""
Civic Commons MCP Server Configuration

Loads environment variables and provides typed configuration.
"""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """Server configuration loaded from environment variables."""
    
    # Database
    database_url: str
    
    # Authentication
    api_key: str
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    
    # Rate limiting
    rate_limit_requests: int = 100
    rate_limit_window: int = 60  # seconds
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable is required")
        
        api_key = os.environ.get("MCP_API_KEY")
        if not api_key:
            raise ValueError("MCP_API_KEY environment variable is required")
        
        return cls(
            database_url=database_url,
            api_key=api_key,
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8080")),
            rate_limit_requests=int(os.environ.get("RATE_LIMIT_REQUESTS", "100")),
            rate_limit_window=int(os.environ.get("RATE_LIMIT_WINDOW", "60")),
        )


# Global config instance (lazy loaded)
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config
