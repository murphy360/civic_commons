"""
Database initialization module

Provides idempotent database initialization that can be safely called
on every startup without causing errors if the database is already initialized.
"""

import logging
import os
import asyncpg
from pathlib import Path

logger = logging.getLogger("civic_commons.db_init")


async def check_database_initialized(pool: asyncpg.Pool) -> bool:
    """Check if the database has been initialized (activity_log table exists)."""
    try:
        async with pool.acquire() as conn:
            result = await conn.fetchval("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_name = 'activity_log'
                )
            """)
            return result
    except Exception as e:
        logger.error(f"Error checking database initialization: {e}")
        return False


async def load_init_script(script_path: str | None = None) -> str:
    """Load the database initialization SQL script."""
    if script_path is None:
        # Default to scripts/init-db.sql relative to this file
        current_dir = Path(__file__).parent.parent.parent
        script_path = current_dir / "scripts" / "init-db.sql"
    else:
        script_path = Path(script_path)
    
    if not script_path.exists():
        raise FileNotFoundError(f"Database initialization script not found: {script_path}")
    
    with open(script_path, 'r') as f:
        return f.read()


async def initialize_database(pool: asyncpg.Pool, script_path: str | None = None) -> bool:
    """
    Initialize the database with schema and data if not already done.
    
    This is idempotent - safe to call multiple times. If the database is
    already initialized, it returns True without making any changes.
    
    Args:
        pool: asyncpg connection pool
        script_path: Optional path to init script (defaults to scripts/init-db.sql)
    
    Returns:
        True if initialization succeeded (or was not needed)
        False if initialization failed
    """
    try:
        # Check if already initialized
        is_initialized = await check_database_initialized(pool)
        if is_initialized:
            logger.info("✓ Database already initialized")
            return True
        
        logger.info("⏳ Initializing database schema...")
        
        # Load and execute initialization script
        init_script = await load_init_script(script_path)
        
        async with pool.acquire() as conn:
            await conn.execute(init_script)
        
        logger.info("✓ Database schema initialized successfully")
        return True
    
    except Exception as e:
        logger.error(f"✗ Database initialization failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
