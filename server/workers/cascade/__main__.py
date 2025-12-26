"""
Entry point for cascade worker when run as a module.
Sets up sys.path so relative imports work correctly.
"""
import sys
from pathlib import Path

# Add cascade directory to path
cascade_dir = Path(__file__).parent
sys.path.insert(0, str(cascade_dir))

# Now run main
from cascade_service import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())
