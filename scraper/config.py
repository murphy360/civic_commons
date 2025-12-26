"""
Purpose: Configuration loading and validation using Pydantic
Dependencies: Pydantic for validation, PyYAML for parsing
Consumed by: main.py, all modules that need configuration
Side effects: Reads YAML files from /configs directory
"""

import os
from datetime import datetime
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

    # MCP Server (for event deduplication and unified management)
    mcp_url: str = "http://localhost:8000"
    
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
    entity: str | None = None  # Reference to entity key


class CityProfile(BaseModel):
    """City identity information."""
    name: str
    zip: str
    timezone: str  # Required - must be set in config (e.g., "America/New_York")
    data_start_date: str | None = None  # ISO date string (e.g., "2025-01-01") - no data before this date


class AssistantConfig(BaseModel):
    """Bot personality configuration."""
    name: str = "Assistant"
    persona: str = "A helpful assistant for local civic information."


class ColorSchemeConfig(BaseModel):
    """Color scheme for a domain (civic, education, etc.)."""
    primary: str  # Tailwind color class (e.g., "blue-600")
    light: str    # Light variant (e.g., "blue-100")
    dark: str     # Dark variant (e.g., "blue-800")
    border: str   # Border color (e.g., "blue-300")
    icon: str | None = None  # Default emoji for domain


class EntityConfig(BaseModel):
    """Configuration for a civic entity (organization/body)."""
    display_name: str
    short_name: str | None = None
    domain: str  # civic, education, community, recreation, business
    type: str | None = None  # municipality, legislative_body, commission, board, school, etc.
    parent: str | None = None  # Parent entity key
    aliases: list[str] = Field(default_factory=list)
    icon: str | None = None  # Emoji icon


class CityConfig(BaseModel):
    """Complete configuration for a city deployment."""
    city_profile: CityProfile
    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    color_schemes: dict[str, ColorSchemeConfig] = Field(default_factory=dict)
    entities: dict[str, EntityConfig] = Field(default_factory=dict)
    sources: list[SourceConfig] = Field(default_factory=list)
    private_sources: list[SourceConfig] = Field(default_factory=list)
    # Top-level data_start_date for backward compatibility
    data_start_date: str | None = None  # ISO date string (e.g., "2025-01-01")

    def get_data_start_date(self) -> datetime | None:
        """Get the data start date as a datetime object. Returns None if not set."""
        date_str = self.data_start_date
        if date_str:
            try:
                return datetime.fromisoformat(date_str)
            except ValueError:
                return None
        return None

    @property
    def all_enabled_sources(self) -> list[SourceConfig]:
        """Get all enabled sources (public + private)."""
        enabled = [s for s in self.sources if s.enabled]
        enabled.extend([s for s in self.private_sources if s.enabled])
        return enabled

    def get_entity(self, entity_key: str | None) -> EntityConfig | None:
        """Get entity config by key."""
        if not entity_key:
            return None
        return self.entities.get(entity_key)

    def get_entity_for_source(self, source: SourceConfig) -> EntityConfig | None:
        """Get the entity associated with a source."""
        return self.get_entity(source.entity)

    def get_color_scheme(self, domain: str) -> ColorSchemeConfig | None:
        """Get color scheme for a domain."""
        return self.color_schemes.get(domain)

    def get_entity_color_scheme(self, entity_key: str | None) -> ColorSchemeConfig | None:
        """Get color scheme for an entity's domain."""
        entity = self.get_entity(entity_key)
        if entity:
            return self.get_color_scheme(entity.domain)
        return None

    def validate_entity_references(self) -> list[str]:
        """
        Validate that all entity references in sources exist.
        Returns list of warning messages for invalid references.
        """
        warnings = []
        for source in self.sources + self.private_sources:
            if source.entity and source.entity not in self.entities:
                warnings.append(
                    f"Source '{source.name}' references unknown entity '{source.entity}'"
                )
        
        # Validate parent references in entities
        for key, entity in self.entities.items():
            if entity.parent and entity.parent not in self.entities:
                warnings.append(
                    f"Entity '{key}' references unknown parent '{entity.parent}'"
                )
        
        return warnings


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
    
    config = CityConfig(**data)
    
    # Validate entity references and log warnings
    warnings = config.validate_entity_references()
    for warning in warnings:
        print(f"Warning in {path.name}: {warning}")
    
    return config


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
