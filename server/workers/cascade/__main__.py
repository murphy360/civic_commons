"""
Entry point for cascade worker when run as a module.
Sets up sys.path so relative imports work correctly.
"""
import sys
import logging
from pathlib import Path

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,  # Ensure output goes to stdout for Docker
    force=True,  # Force reconfiguration
)

# Add cascade directory to path
cascade_dir = Path(__file__).parent
sys.path.insert(0, str(cascade_dir))

# Now run main
from cascade_service import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
