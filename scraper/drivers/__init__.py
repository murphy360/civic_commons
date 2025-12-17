"""
Purpose: Export driver registry and lookup function
Dependencies: All driver implementations
Consumed by: main.py
Side effects: None
"""

from typing import Type

from .base import BaseDriver
from .civic_plus import CivicPlusDriver
from .civic_plus_calendar import CivicPlusCalendarDriver
from .civic_plus_rss import CivicPlusRssDriver
from .civicplus_document_center import CivicPlusDocumentCenterDriver
from .aspnet_generic import AspNetGenericDriver
from .rss import RssDriver
from .libcal import LibCalDriver
from .icalendar_driver import ICalendarDriver
from .youtube_channel import YouTubeChannelDriver
from .tcsd_agendas import TCSDagendasDriver

# Driver registry: maps driver name to class
DRIVER_REGISTRY: dict[str, Type[BaseDriver]] = {
    "civic_plus": CivicPlusDriver,
    "civic_plus_calendar": CivicPlusCalendarDriver,
    "civic_plus_rss": CivicPlusRssDriver,
    "civicplus_document_center": CivicPlusDocumentCenterDriver,
    "aspnet_generic": AspNetGenericDriver,
    "rss": RssDriver,
    "libcal": LibCalDriver,
    "icalendar": ICalendarDriver,
    "youtube_channel": YouTubeChannelDriver,
    "tcsd_agendas": TCSDagendasDriver,
    # Add new drivers here
    # "civic_rec": CivicRecDriver,
    # "metroparks": MetroparksDriver,
}


def get_driver(driver_name: str) -> Type[BaseDriver]:
    """
    Get a driver class by name.
    
    Args:
        driver_name: Name of the driver (from YAML config)
        
    Returns:
        Driver class (not instance)
        
    Raises:
        ValueError: If driver name is not registered
    """
    if driver_name not in DRIVER_REGISTRY:
        available = ", ".join(DRIVER_REGISTRY.keys())
        raise ValueError(
            f"Unknown driver: {driver_name}. Available: {available}"
        )
    return DRIVER_REGISTRY[driver_name]


__all__ = [
    "BaseDriver",
    "get_driver",
    "DRIVER_REGISTRY",
    "CivicPlusDriver",
    "AspNetGenericDriver",
    "RssDriver",
    "LibCalDriver",
]
