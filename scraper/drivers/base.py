"""
Purpose: Abstract base class defining the driver interface
Dependencies: abc for abstract methods, models for Event/Document types
Consumed by: All driver implementations, main.py
Side effects: None
"""

from abc import ABC, abstractmethod
import asyncio
import logging
from typing import Any

from config import SourceConfig, CityConfig
from models import Event, Document

logger = logging.getLogger("civic.driver")


class BaseDriver(ABC):
    """
    Abstract base class for all data source drivers.
    
    Each driver is responsible for:
    1. Connecting to a specific type of data source
    2. Extracting events and documents
    3. Returning normalized Event and Document objects
    
    Drivers should NOT:
    - Write to the database (that's the pipeline's job)
    - Handle scheduling (that's the worker's job)
    - Perform AI summarization (that's the pipeline's job)
    """

    def __init__(
        self,
        source_config: SourceConfig,
        city_config: CityConfig,
    ):
        """
        Initialize the driver.
        
        Args:
            source_config: Configuration for this specific source
            city_config: Configuration for the city (for context)
        """
        self.source_config = source_config
        self.city_config = city_config
        self.params = source_config.params
        self.rate_limit = source_config.rate_limit
        
        # For logging context
        self.source_name = source_config.name
        self.city_name = city_config.city_profile.name

    @abstractmethod
    async def fetch(self) -> tuple[list[Event], list[Document]]:
        """
        Fetch events and documents from the source.
        
        This is the main method that subclasses must implement.
        
        Returns:
            Tuple of (events, documents) lists
            
        Raises:
            Any exception on failure (will be caught by worker)
        """
        pass

    async def fetch_events(self) -> list[Event]:
        """
        Convenience method to fetch only events.
        
        Default implementation calls fetch() and returns events.
        Override if your source only has events.
        """
        events, _ = await self.fetch()
        return events

    async def fetch_documents(self) -> list[Document]:
        """
        Convenience method to fetch only documents.
        
        Default implementation calls fetch() and returns documents.
        Override if your source only has documents.
        """
        _, documents = await self.fetch()
        return documents

    async def rate_limit_delay(self) -> None:
        """Apply rate limiting delay between requests."""
        delay = self.rate_limit.delay_seconds
        if delay > 0:
            logger.debug(f"Rate limit: sleeping {delay}s")
            await asyncio.sleep(delay)

    def log_info(self, message: str) -> None:
        """Log an info message with source context."""
        logger.info(f"[{self.city_name}/{self.source_name}] {message}")

    def log_error(self, message: str, exc: Exception | None = None) -> None:
        """Log an error message with source context."""
        logger.error(
            f"[{self.city_name}/{self.source_name}] {message}",
            exc_info=exc,
        )

    def log_debug(self, message: str) -> None:
        """Log a debug message with source context."""
        logger.debug(f"[{self.city_name}/{self.source_name}] {message}")
