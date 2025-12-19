"""
Purpose: Configuration loading and validation using Pydantic
Dependencies: Pydantic for validation, PyYAML for parsing
Consumed by: main.py, all modules that need configuration
Side effects: Reads YAML files from /configs directory
"""

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


# =============================================================================
# ENVIRONMENT SETTINGS
# =============================================================================

class Settings(BaseSettings):
    """Application settings from environment variables."""
    
    # Database - can use DATABASE_URL directly OR individual components
    database_url: str | None = None
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "civic_commons"
    postgres_user: str = "commons"
    postgres_password: str = ""

    # Paths
    configs_dir: str = "/app/configs"
    
    # Behavior
    run_on_startup: bool = False
    log_level: str = "INFO"
    
    # AI Queue Processing Configuration
    ai_queue_interval_seconds: int = 30  # How often the queue runs
    ai_queue_batch_size: int = 1  # Items processed per run
    ai_summary_max_age_days: int = 0  # Only summarize items newer than this (0 = no limit)

    def get_database_url(self) -> str:
        """Get database URL - use DATABASE_URL if set, otherwise construct from parts."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# =============================================================================
# YAML CONFIGURATION MODELS
# =============================================================================

class RateLimitConfig(BaseModel):
    """Rate limiting configuration for a source."""
    delay_seconds: float = 2.0
    max_concurrent: int = 1


class RetryConfig(BaseModel):
    """Retry configuration for a source."""
    max_attempts: int = 3
    backoff_seconds: float = 60.0


class SourceConfig(BaseModel):
    """Configuration for a single data source."""
    name: str
    driver: str
    schedule: str  # Cron expression
    params: dict[str, Any] = Field(default_factory=dict)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    enabled: bool = True


class CityProfile(BaseModel):
    """City identity information."""
    name: str
    zip: str
    timezone: str  # Required - must be set in config (e.g., "America/New_York")


class AssistantConfig(BaseModel):
    """Bot personality configuration."""
    name: str = "Assistant"
    persona: str = "A helpful assistant for local civic information."


class CityConfig(BaseModel):
    """Complete configuration for a city deployment."""
    city_profile: CityProfile
    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    sources: list[SourceConfig] = Field(default_factory=list)
    private_sources: list[SourceConfig] = Field(default_factory=list)

    @property
    def all_enabled_sources(self) -> list[SourceConfig]:
        """Get all enabled sources (public + private)."""
        enabled = [s for s in self.sources if s.enabled]
        enabled.extend([s for s in self.private_sources if s.enabled])
        return enabled


# =============================================================================
# LOADING FUNCTIONS
# =============================================================================

def load_config(path: Path) -> CityConfig:
    """
    Load a single city configuration from a YAML file.
    
    Args:
        path: Path to the YAML configuration file
        
    Returns:
        Validated CityConfig object
        
    Raises:
        ValueError: If the configuration is invalid
        FileNotFoundError: If the file doesn't exist
    """
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    return CityConfig(**data)


def load_all_configs(configs_dir: Path) -> list[CityConfig]:
    """
    Load all city configurations from a directory.
    
    Args:
        configs_dir: Path to directory containing YAML files
        
    Returns:
        List of validated CityConfig objects
        
    Notes:
        - Skips files starting with underscore (templates)
        - Skips non-YAML files
    """
    configs = []
    
    if not configs_dir.exists():
        raise FileNotFoundError(f"Configs directory not found: {configs_dir}")

    for yaml_file in configs_dir.glob("*.yaml"):
        # Skip templates
        if yaml_file.name.startswith("_"):
            continue
            
        try:
            config = load_config(yaml_file)
            configs.append(config)
        except Exception as e:
            # Log but don't fail entirely
            print(f"Warning: Failed to load {yaml_file}: {e}")
            continue

    return configs
