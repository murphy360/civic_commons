"""
Document linking pipeline - links documents to events.

Provides date-based and AI-assisted linking strategies.
"""

import logging
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger("civic.document_linker")


class DocumentLinker:
    """Links documents to events using date matching and AI assistance."""

    def __init__(self, db_pool, ai_processor=None):
        self.db_pool = db_pool
        self.ai_processor = ai_processor

    async def get_date_linkable_count(self, conn) -> int:
        """Count documents that can be linked by date match."""
        result = await conn.fetchval("""
            SELECT COUNT(*)
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND (d.linking_status IS NULL OR d.linking_status IN ('pending', 'pending_retry'))
              AND (d.linking_retry_after IS NULL OR d.linking_retry_after <= NOW())
              AND d.meeting_date IS NOT NULL
              AND d.document_type NOT IN ('ordinance', 'resolution')
        """)
        return result or 0

    async def get_ai_linkable_count(self, conn) -> int:
        """Count documents that need AI linking (have summary but not date-linked)."""
        result = await conn.fetchval("""
            SELECT COUNT(*)
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND (d.linking_status IS NULL OR d.linking_status IN ('pending', 'needs_summary'))
              AND d.ai_summary IS NOT NULL AND d.ai_summary != ''
        """)
        return result or 0

    async def process_date_based_linking(self, conn) -> int:
        """
        Phase 1: Link documents by date match (NO AI, NO SPEED LIMIT).
        
        Processes ALL documents that have meeting_date and can be linked
        by exact date match. This is fast and doesn't use AI.
        """
        # Mark ordinances/resolutions as standalone
        standalone_updated = await conn.execute("""
            UPDATE documents 
            SET linking_status = 'not_applicable'
            WHERE document_type IN ('ordinance', 'resolution')
              AND (linking_status IS NULL OR linking_status IN ('pending', 'pending_retry'))
        """)
        if standalone_updated and 'UPDATE' in standalone_updated:
            count = int(standalone_updated.split()[1]) if len(standalone_updated.split()) > 1 else 0
            if count > 0:
                logger.info(f"Marked {count} ordinances/resolutions as standalone")

        # Get ALL date-linkable documents
        docs = await conn.fetch("""
            SELECT d.id, d.title, d.document_type, d.meeting_date, d.source_id,
                   d.linking_status, d.linking_attempts
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND (d.linking_status IS NULL OR d.linking_status IN ('pending', 'pending_retry'))
              AND (d.linking_retry_after IS NULL OR d.linking_retry_after <= NOW())
              AND d.meeting_date IS NOT NULL
              AND d.document_type NOT IN ('ordinance', 'resolution')
            ORDER BY d.meeting_date DESC, d.created_at DESC
        """)

        if not docs:
            logger.debug("No documents pending date-based linking")
            return 0

        logger.info(f"Date-linking {len(docs)} documents")
        linked_count = 0

        for doc in docs:
            try:
                linked = await self._link_document_by_date(conn, doc)
                if linked:
                    linked_count += 1
            except Exception as e:
                logger.warning(f"Date-linking failed for '{doc['title']}': {e}")

        logger.info(f"Date-linking complete - {linked_count} documents linked")
        return linked_count

    async def _link_document_by_date(self, conn, doc: dict) -> bool:
        """Attempt to link a single document by date match."""
        attempts = (doc.get("linking_attempts") or 0) + 1
        meeting_date = doc["meeting_date"]
        doc_date = meeting_date.date() if hasattr(meeting_date, 'date') else meeting_date

        # Find events on the exact date
        if doc["document_type"] == "video":
            events = await conn.fetch("""
                SELECT DISTINCT e.id, e.title, e.start_time, e.category
                FROM events e
                JOIN event_sources es ON e.id = es.event_id
                JOIN sources s ON es.source_id = s.id
                WHERE s.city_id = (SELECT city_id FROM sources WHERE id = $1)
                  AND DATE(e.start_time) = $2
                ORDER BY e.start_time DESC
            """, doc["source_id"], doc_date)
        else:
            events = await conn.fetch("""
                SELECT e.id, e.title, e.start_time, e.category
                FROM events e
                JOIN event_sources es ON e.id = es.event_id
                WHERE es.source_id = $1
                  AND DATE(e.start_time) = $2
                ORDER BY e.start_time DESC
            """, doc["source_id"], doc_date)

        if not events:
            # No events - create one if possible
            if doc["document_type"] in ("agenda", "minutes", "video"):
                event_id = await self._create_event_from_document(conn, doc)
                if event_id:
                    await self.db_pool.link_document_to_event(conn, doc["id"], event_id)
                    await conn.execute("""
                        UPDATE documents SET linking_status = 'linked', linking_attempts = $2 WHERE id = $1
                    """, doc["id"], attempts)
                    logger.info(f"Created event from '{doc['title']}' and linked")
                    return True

            # Mark for retry
            await conn.execute("""
                UPDATE documents 
                SET linking_status = 'pending_retry', 
                    linking_attempts = $2,
                    linking_retry_after = NOW() + INTERVAL '1 hour'
                WHERE id = $1
            """, doc["id"], attempts)
            return False

        # Try to find best match
        exact_match = self._find_best_event_match(doc, events)

        if exact_match:
            await self.db_pool.link_document_to_event(conn, doc["id"], exact_match["id"])
            await conn.execute("""
                UPDATE documents SET linking_status = 'linked', linking_attempts = $2 WHERE id = $1
            """, doc["id"], attempts)
            logger.info(f"Date-linked '{doc['title']}' → '{exact_match['title']}'")
            return True
        else:
            # Needs AI assistance
            await conn.execute("""
                UPDATE documents SET linking_status = 'needs_summary' WHERE id = $1
            """, doc["id"])
            logger.debug(f"'{doc['title']}' has multiple events on {doc_date} - needs AI")
            return False

    def _find_best_event_match(self, doc: dict, events: list) -> Optional[dict]:
        """Find the best matching event for a document."""
        if len(events) == 1:
            return events[0]

        doc_title_lower = doc["title"].lower()
        best_match, best_score = None, 0

        meeting_types = [
            "city council", "council", "planning commission", "planning",
            "zoning", "board of zoning", "finance", "finance committee",
            "parks", "recreation", "school board", "board of education",
            "township", "trustees",
        ]

        for e in events:
            event_title_lower = e["title"].lower()
            event_category_lower = (e["category"] or "").lower()
            score = 0

            for meeting_type in meeting_types:
                if meeting_type in doc_title_lower:
                    if meeting_type in event_title_lower or meeting_type in event_category_lower:
                        score += 10
                    else:
                        score -= 5

            event_words = set(event_title_lower.split())
            doc_words = set(doc_title_lower.split())
            common = event_words & doc_words - {"meeting", "agenda", "minutes", "the", "of", "and", "for"}
            score += len(common) * 2

            if score > best_score:
                best_score, best_match = score, e

        return best_match if best_match and best_score > 0 else None

    async def _create_event_from_document(self, conn, doc: dict) -> Optional[int]:
        """Create an event from an agenda, minutes, or video document."""
        title = doc["title"]
        meeting_date = doc["meeting_date"]
        source_id = doc["source_id"]

        # Parse event title from document title
        event_title = title
        for suffix in [" - Agenda", " - Minutes", " - Video", " Agenda", " Minutes", " Video",
                       " - agenda", " - minutes", " - video"]:
            if event_title.endswith(suffix):
                event_title = event_title[:-len(suffix)]
                break

        # Remove date patterns
        event_title = re.sub(r'\s*-?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*$', '', event_title)
        event_title = re.sub(r'\s*-?\s*\w+ \d{1,2},? \d{4}\s*$', '', event_title)
        event_title = re.sub(
            r'\s*-?\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\s*$',
            '', event_title, flags=re.IGNORECASE
        )
        event_title = event_title.rstrip(' -').strip() or "Meeting"

        # Determine category
        category = self._infer_category(event_title)

        # Convert date to datetime
        if hasattr(meeting_date, 'date'):
            start_time = meeting_date
        else:
            start_time = datetime.combine(meeting_date, datetime.min.time())

        try:
            row = await conn.fetchrow("""
                INSERT INTO events (title, start_time, category, created_at, updated_at)
                VALUES ($1, $2, $3, NOW(), NOW())
                RETURNING id
            """, event_title, start_time, category)

            event_id = row["id"]

            await conn.execute("""
                INSERT INTO event_sources (event_id, source_id, first_seen_at, last_seen_at)
                VALUES ($1, $2, NOW(), NOW())
                ON CONFLICT (event_id, source_id) DO NOTHING
            """, event_id, source_id)

            logger.info(f"Created event '{event_title}' on {start_time.date()}")
            return event_id

        except Exception as e:
            logger.warning(f"Failed to create event from '{title}': {e}")
            return None

    def _infer_category(self, title: str) -> str:
        """Infer event category from title."""
        title_lower = title.lower()
        if "council" in title_lower:
            return "city_council"
        elif "planning" in title_lower:
            return "planning_commission"
        elif "zoning" in title_lower:
            return "zoning_board"
        elif "school" in title_lower or "education" in title_lower:
            return "school_board"
        elif "finance" in title_lower:
            return "finance_committee"
        elif "parks" in title_lower or "recreation" in title_lower:
            return "parks_recreation"
        elif "committee" in title_lower:
            return "committee"
        return "meeting"

    async def process_ai_linking(self, conn, batch_size: int) -> int:
        """Phase 2: Link documents using AI (for docs with summaries but no date match)."""
        if not self.ai_processor or not self.ai_processor.enabled:
            return 0

        docs = await conn.fetch("""
            SELECT d.id, d.title, d.document_type, d.ai_summary, d.meeting_date, d.source_id,
                   d.linking_status, d.linking_attempts
            FROM documents d
            LEFT JOIN event_documents ed ON d.id = ed.document_id
            WHERE ed.document_id IS NULL
              AND (d.linking_status IS NULL OR d.linking_status IN ('pending', 'needs_summary'))
              AND d.ai_summary IS NOT NULL AND d.ai_summary != ''
            ORDER BY d.created_at DESC
            LIMIT $1
        """, batch_size)

        if not docs:
            logger.debug("No documents pending AI linking")
            return 0

        logger.info(f"AI-linking {len(docs)} documents")
        linked_count = 0

        for doc in docs:
            try:
                linked = await self._link_document_with_ai(conn, doc)
                if linked:
                    linked_count += 1
            except Exception as e:
                logger.warning(f"AI linking failed for '{doc['title']}': {e}")

        logger.info(f"AI-linking complete - {linked_count} documents linked")
        return linked_count

    async def _link_document_with_ai(self, conn, doc: dict) -> bool:
        """Link a single document using AI."""
        attempts = (doc.get("linking_attempts") or 0) + 1
        meeting_date = doc["meeting_date"] or datetime.now()

        events = await conn.fetch("""
            SELECT e.id, e.title, e.start_time, e.category
            FROM events e
            JOIN event_sources es ON e.id = es.event_id
            WHERE es.source_id = $1
              AND e.start_time BETWEEN ($2::timestamp - INTERVAL '30 days') AND ($2::timestamp + INTERVAL '30 days')
            ORDER BY e.start_time DESC
            LIMIT 20
        """, doc["source_id"], meeting_date)

        if not events:
            await conn.execute("""
                UPDATE documents 
                SET linking_status = 'pending_retry', linking_attempts = $2,
                    linking_retry_after = NOW() + INTERVAL '1 hour'
                WHERE id = $1
            """, doc["id"], attempts)
            return False

        events_context = [
            {"id": e["id"], "title": e["title"],
             "date": e["start_time"].isoformat() if e["start_time"] else None,
             "type": e["category"]}
            for e in events
        ]

        matches = await self.ai_processor.find_related_events(
            document_title=doc["title"],
            document_type=doc["document_type"],
            document_content=doc["ai_summary"],
            events=events_context,
        )

        if matches:
            for match in matches:
                await self.db_pool.link_document_to_event(
                    conn, doc["id"], match["event_id"],
                    confidence=match.get("confidence", 0.5),
                )
            await conn.execute("""
                UPDATE documents SET linking_status = 'linked', linking_attempts = $2 WHERE id = $1
            """, doc["id"], attempts)
            logger.info(f"AI-linked '{doc['title']}' to {len(matches)} event(s)")
            return True
        else:
            if attempts >= 3:
                await conn.execute("""
                    UPDATE documents SET linking_status = 'blocked', linking_attempts = $2 WHERE id = $1
                """, doc["id"], attempts)
                logger.info(f"Blocked '{doc['title']}' after {attempts} attempts")
            else:
                await conn.execute("""
                    UPDATE documents 
                    SET linking_status = 'pending_retry', linking_attempts = $2,
                        linking_retry_after = NOW() + INTERVAL '1 hour'
                    WHERE id = $1
                """, doc["id"], attempts)
            return False
