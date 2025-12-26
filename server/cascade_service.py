"""
Cascade Service - Background worker for summary regeneration.

Monitors the database for documents/events that have been processed and need
their parent summaries regenerated. Runs as a separate service/daemon.

Responsibilities:
- Periodically check for documents with new AI summaries
- Mark document's event and parent period summaries as stale
- Track which documents have had cascade triggered (idempotent)

This is a standalone service that can run independently, called via HTTP
to the MCP server's cascade_tools endpoints.
"""

import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("civic_commons.cascade_service")


class CascadeService:
    """
    Background service that monitors and triggers summary cascades.
    
    Runs independently, queries database periodically, and calls
    MCP server endpoints to trigger cascade updates.
    """
    
    def __init__(self, mcp_url: str = "http://localhost:8000", db_url: Optional[str] = None):
        """
        Initialize cascade service.
        
        Args:
            mcp_url: URL of MCP server (default: localhost:8000)
            db_url: Database URL (optional - can be loaded from env)
        """
        self.mcp_url = mcp_url.rstrip("/")
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self._http_client: Optional[httpx.AsyncClient] = None
        self._running = False
    
    async def start(self) -> None:
        """Start the cascade service."""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._running = True
        logger.info(f"Cascade service started (MCP: {self.mcp_url})")
        
        try:
            await self._monitor_loop()
        except asyncio.CancelledError:
            logger.info("Cascade service cancelled")
        except Exception as e:
            logger.error(f"Cascade service error: {e}")
        finally:
            await self.stop()
    
    async def stop(self) -> None:
        """Stop the cascade service."""
        self._running = False
        if self._http_client:
            await self._http_client.aclose()
        logger.info("Cascade service stopped")
    
    async def _monitor_loop(self) -> None:
        """
        Main monitoring loop.
        
        Periodically checks for:
        1. Documents with new AI summaries that haven't had cascade triggered
        2. Calls MCP server to mark summaries as stale
        3. Marks document as cascade_triggered to avoid re-processing
        """
        import asyncpg
        
        # Connect to database
        db_pool = await asyncpg.create_pool(self.db_url, min_size=1, max_size=5)
        
        try:
            while self._running:
                try:
                    await asyncio.sleep(60)  # Check every minute
                    
                    async with db_pool.acquire() as conn:
                        # Find documents with AI summaries that need cascade
                        docs = await conn.fetch("""
                            SELECT 
                                d.id,
                                ed.event_id,
                                s.city_id
                            FROM documents d
                            JOIN event_documents ed ON d.id = ed.document_id
                            JOIN sources s ON d.source_id = s.id
                            WHERE d.ai_summary IS NOT NULL
                              AND d.ai_summary != ''
                              AND (d.cascade_triggered_at IS NULL 
                                   OR d.cascade_triggered_at < d.updated_at)
                              AND d.updated_at > NOW() - INTERVAL '2 hours'
                            ORDER BY d.updated_at DESC
                            LIMIT 10
                        """)
                        
                        if not docs:
                            continue
                        
                        logger.debug(f"Found {len(docs)} documents needing cascade")
                        
                        for doc in docs:
                            success = await self._trigger_cascade(
                                document_id=doc["id"],
                                event_id=doc["event_id"],
                                city_id=doc["city_id"],
                            )
                            
                            if success:
                                # Mark as cascade triggered
                                await conn.execute(
                                    "UPDATE documents SET cascade_triggered_at = NOW() WHERE id = $1",
                                    doc["id"]
                                )
                                logger.info(f"Cascade triggered for document {doc['id']}")
                            else:
                                logger.warning(f"Cascade failed for document {doc['id']}")
                
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in cascade monitor loop: {e}")
                    await asyncio.sleep(60)
        
        finally:
            await db_pool.close()
    
    async def _trigger_cascade(
        self, document_id: int, event_id: int, city_id: str
    ) -> bool:
        """
        Call MCP server to trigger cascade for a document.
        
        Args:
            document_id: Document that was processed
            event_id: Event the document is linked to
            city_id: City identifier
            
        Returns:
            True if cascade was triggered successfully
        """
        try:
            response = await self._http_client.post(
                f"{self.mcp_url}/trigger_cascade_for_document",
                params={
                    "document_id": document_id,
                    "event_id": event_id,
                    "city_id": city_id,
                },
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("success", False)
            else:
                logger.warning(
                    f"Cascade endpoint returned {response.status_code}: {response.text}"
                )
                return False
        
        except Exception as e:
            logger.error(f"Error calling cascade endpoint: {e}")
            return False


async def main():
    """Run cascade service."""
    import signal
    
    mcp_url = os.getenv("MCP_URL", "http://localhost:8000")
    db_url = os.getenv("DATABASE_URL")
    
    service = CascadeService(mcp_url=mcp_url, db_url=db_url)
    
    # Handle signals
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Signal received, stopping service...")
        asyncio.create_task(service.stop())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    asyncio.run(main())
