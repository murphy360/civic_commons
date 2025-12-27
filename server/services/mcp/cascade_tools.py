"""
Summary cascade MCP tool.

Pure tool for marking summaries as stale. This is called by the
cascade_service when documents are processed.

This tool does NOT contain monitoring logic - it only:
- Takes a document ID and its linked event
- Marks the event summary as stale
- Marks parent period summaries (day/week/month) as stale
- Returns success/failure

The cascade_service handles the monitoring and decides when to call this.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger("civic_commons.cascade_tools")


async def trigger_cascade_for_document(
    db: Any,
    document_id: int,
    event_id: int,
    city_id: str,
) -> dict[str, Any]:
    """
    Mark event and parent period summaries as stale.
    
    When a document is processed and linked to an event:
    1. Mark the event summary as stale
    2. Mark parent day/week/month summaries as stale
    
    The AIQueueProcessor will regenerate these summaries on next run.
    This allows summaries to be updated without thrashing - we batch
    multiple changes before regenerating.
    
    Args:
        db: Server Database instance
        document_id: Document that was processed
        event_id: Event the document is linked to
        city_id: City identifier
        
    Returns:
        {
            "success": bool,
            "summaries_marked": int,
            "event_date": str (ISO format),
            "reasoning": str,
            "error": str | null
        }
    """
    try:
        async with db.pool.acquire() as conn:
            # Get event date
            event = await conn.fetchrow(
                "SELECT id, title, start_time FROM events WHERE id = $1",
                event_id,
            )
            
            if not event:
                return {
                    "success": False,
                    "summaries_marked": 0,
                    "event_date": None,
                    "reasoning": f"Event {event_id} not found",
                    "error": f"Event {event_id} not found",
                }
            
            event_date = event["start_time"]
            summaries_marked = 0
            
            # Mark event summary as stale
            marked = await _mark_summary_stale(
                conn, city_id, "event", event_date, event_id,
                triggered_by_document=document_id,
                trigger_reason="document_added"
            )
            summaries_marked += marked
            
            # Cascade up: mark day, week, month, quarter, annual summaries as stale
            for period_type in ["daily", "weekly", "monthly", "quarterly", "annual"]:
                period_count = await _mark_period_summaries_stale(
                    conn, city_id, period_type, event_date,
                    trigger_reason="child_document_added"
                )
                summaries_marked += period_count
            
            logger.info(
                f"Cascade triggered for document {document_id}: "
                f"marked {summaries_marked} summaries as stale"
            )
            
            return {
                "success": True,
                "summaries_marked": summaries_marked,
                "event_date": event_date.isoformat() if event_date else None,
                "reasoning": f"Marked event and {summaries_marked - 1} period summaries for regeneration",
                "error": None,
            }
            
    except Exception as e:
        logger.error(f"Error triggering cascade for document {document_id}: {e}")
        return {
            "success": False,
            "summaries_marked": 0,
            "event_date": None,
            "reasoning": None,
            "error": str(e),
        }


async def _mark_summary_stale(
    conn: Any,
    city_id: str,
    summary_type: str,  # "event", "day", "week", "month"
    date_: datetime,
    entity_id: Optional[int] = None,
    triggered_by_document: Optional[int] = None,
    trigger_reason: Optional[str] = None,
) -> int:
    """
    Mark a summary as stale in the database.
    
    Args:
        conn: Database connection
        city_id: City identifier
        summary_type: Type of summary ("event", "day", "week", "month")
        date_: Date for the summary
        entity_id: Entity ID if type is "event"
        triggered_by_document: Document that triggered this
        trigger_reason: Reason for marking stale
        
    Returns:
        1 if marked, 0 if not found
    """
    try:
        # Check if summary exists
        exists = await conn.fetchval(
            """
            SELECT 1 FROM summaries
            WHERE city_id = $1 AND summary_type = $2 AND summary_date = $3
            """,
            city_id, summary_type, date_.date()
        )
        
        if exists:
            # Mark as stale
            await conn.execute(
                """
                UPDATE summaries
                SET is_stale = true,
                    triggered_by_document = $4,
                    trigger_reason = $5,
                    updated_at = NOW()
                WHERE city_id = $1 AND summary_type = $2 AND summary_date = $3
                """,
                city_id, summary_type, date_.date(),
                triggered_by_document, trigger_reason
            )
            return 1
        else:
            # Create stale entry for future generation
            await conn.execute(
                """
                INSERT INTO summaries 
                (city_id, summary_type, summary_date, is_stale, 
                 triggered_by_document, trigger_reason, created_at, updated_at)
                VALUES ($1, $2, $3, true, $4, $5, NOW(), NOW())
                ON CONFLICT (city_id, summary_type, summary_date) 
                DO UPDATE SET 
                    is_stale = true,
                    triggered_by_document = $4,
                    trigger_reason = $5,
                    updated_at = NOW()
                """,
                city_id, summary_type, date_.date(),
                triggered_by_document, trigger_reason
            )
            return 1
            
    except Exception as e:
        logger.warning(f"Error marking {summary_type} summary stale: {e}")
        return 0


async def _mark_period_summaries_stale(
    conn: Any,
    city_id: str,
    period_type: str,  # "daily", "weekly", "monthly", "quarterly", "annual"
    event_date: datetime,
    trigger_reason: Optional[str] = None,
) -> int:
    """
    Mark all period summaries that contain the event_date as stale.
    
    For "daily": marks that day
    For "weekly": marks the week containing event_date
    For "monthly": marks the month containing event_date
    For "quarterly": marks the quarter containing event_date
    For "annual": marks the year containing event_date
    
    Args:
        conn: Database connection
        city_id: City identifier
        period_type: Type of period ("daily", "weekly", "monthly", "quarterly", "annual")
        event_date: Reference date
        trigger_reason: Reason for marking
        
    Returns:
        Count of summaries marked
    """
    try:
        if period_type == "daily":
            # Same date
            period_start = event_date.replace(hour=0, minute=0, second=0, microsecond=0)
            period_end = period_start + timedelta(days=1)
        
        elif period_type == "weekly":
            # Week containing this date (Monday-Sunday)
            period_start = event_date - timedelta(days=event_date.weekday())
            period_start = period_start.replace(hour=0, minute=0, second=0, microsecond=0)
            period_end = period_start + timedelta(days=7)
        
        elif period_type == "monthly":
            # First day of month containing this date
            period_start = event_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # End is first day of next month
            if period_start.month == 12:
                period_end = period_start.replace(year=period_start.year + 1, month=1)
            else:
                period_end = period_start.replace(month=period_start.month + 1)
        
        elif period_type == "quarterly":
            # Quarter containing this date (Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec)
            quarter = (event_date.month - 1) // 3
            quarter_start_month = quarter * 3 + 1
            period_start = event_date.replace(month=quarter_start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
            # End is first day of next quarter
            if quarter == 3:  # Q4
                period_end = period_start.replace(year=period_start.year + 1, month=1)
            else:
                period_end = period_start.replace(month=quarter_start_month + 3)
        
        elif period_type == "annual":
            # Year containing this date
            period_start = event_date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            period_end = period_start.replace(year=period_start.year + 1)
        
        else:
            logger.warning(f"Unknown period type: {period_type}")
            return 0
        
        # Mark existing summary as stale, or create a pending one
        result = await conn.execute(
            """
            UPDATE summaries
            SET status = 'stale',
                is_stale = true,
                trigger_reason = $5,
                updated_at = NOW()
            WHERE city_id = $1 
              AND summary_type = $2 
              AND period_start = $3
              AND period_end = $4
            """,
            city_id, period_type, period_start, period_end, trigger_reason
        )
        
        # Check if we updated anything
        if result == "UPDATE 0":
            # Create a pending summary entry
            await conn.execute(
                """
                INSERT INTO summaries 
                (city_id, summary_type, period_start, period_end, status, is_stale, 
                 trigger_reason, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'pending', true, $5, NOW(), NOW())
                ON CONFLICT (city_id, summary_type, period_start, period_end) 
                DO UPDATE SET 
                    status = 'stale',
                    is_stale = true,
                    trigger_reason = $5,
                    updated_at = NOW()
                """,
                city_id, period_type, period_start, period_end, trigger_reason
            )
        
        logger.debug(f"Marked {period_type} summary as stale for {city_id}: {period_start} - {period_end}")
        return 1
        
    except Exception as e:
        logger.warning(f"Error marking {period_type} summaries stale: {e}")
        return 0


