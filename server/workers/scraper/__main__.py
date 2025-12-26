"""
Entry point for scraper worker when run as a module.
Sets up sys.path so relative imports work correctly.
"""
import sys
from pathlib import Path

# Add scraper directory to path so "from config import" works
scraper_dir = Path(__file__).parent
sys.path.insert(0, str(scraper_dir))

# Now run main
from main import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
