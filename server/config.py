"""
Civic Commons MCP Server Configuration

Loads environment variables and provides typed configuration.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


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
_city_config: dict | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


def get_city_config() -> dict:
    """
    Load city configuration from YAML file.
    
    Uses DEFAULT_CONFIG env var to find the config file.
    Returns dict with city_profile, assistant, sources.
    """
    global _city_config
    if _city_config is not None:
        return _city_config
    
    # Find config file
    config_name = os.environ.get("DEFAULT_CONFIG", "twinsburg.yaml")
    
    # Look in several locations
    search_paths = [
        Path(f"/app/configs/{config_name}"),  # Docker
        Path(f"../configs/{config_name}"),     # Local dev from server/
        Path(f"configs/{config_name}"),        # Local dev from root
    ]
    
    config_path = None
    for path in search_paths:
        if path.exists():
            config_path = path
            break
    
    if config_path is None:
        # Return defaults if no config found - timezone should be set in config!
        _city_config = {
            "city_profile": {"name": "Community", "zip": "00000", "timezone": "UTC"},
            "assistant": {"name": "Assistant", "persona": "A helpful assistant for local civic information."},
        }
        return _city_config
    
    with open(config_path, "r", encoding="utf-8") as f:
        _city_config = yaml.safe_load(f)
    
    return _city_config
