# Queue System Architecture

This document describes how Civic Commons processes content through its queue-based pipeline.

## Overview

The queue system tracks all content from discovery through AI processing. Every document, video, and event is tracked in the database with a `content_status` field that indicates where it is in the pipeline.

## System Diagram

```
                              ┌─────────────────────────────────────┐
                              │           SCRAPER                   │
                              │   Discovers URLs & Creates Events   │
                              └──────────────┬──────────────────────┘
                                             │
                 ┌───────────────────────────┼───────────────────────────┐
                 ▼                           ▼                           ▼
        ┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
        │   DOCUMENTS     │         │    EVENTS       │         │   SUMMARIES     │
        │  (PDFs, Videos) │         │  (Meetings)     │         │  (Aggregated)   │
        └────────┬────────┘         └────────┬────────┘         └────────┬────────┘
                 │                           │                           │
═══════════════╤═╧═══════════════════════════╪═══════════════════════════╪═════════════════
               │                             │                           │
     ┌─────────┴─────────┐                   │                           │
     ▼                   ▼                   │                           │
┌─────────┐        ┌──────────┐              │                           │
│  PDFs   │        │  VIDEOS  │              │                           │
│ agenda  │        │ YouTube  │              │                           │
│ minutes │        │ Vimeo    │              │                           │
│ legis.  │        │          │              │                           │
└────┬────┘        └────┬─────┘              │                           │
     │                  │                    │                           │
     ▼                  │                    │                           │
┌──────────┐            │                    │                           │
│ DOWNLOAD │            │ (no download       │                           │
│  QUEUE   │            │  needed - uses     │                           │
│          │            │  platform API)     │                           │
└────┬─────┘            │                    │                           │
     │                  │                    │                           │
     ▼                  │                    │                           │
┌──────────┐            │                    │                           │
│  TEXT    │            │                    │                           │
│EXTRACTION│            │                    │                           │
│          │            │                    │                           │
└────┬─────┘            │                    │                           │
     │                  │                    │                           │
     ▼                  ▼                    │                           │
┌──────────┐      ┌───────────┐              │                           │
│ DOC AI   │      │ VIDEO AI  │              │                           │
│ SUMMARY  │      │TRANSCRIBE │              │                           │
│          │      │& SUMMARIZE│              │                           │
└────┬─────┘      └─────┬─────┘              │                           │
     │                  │                    │                           │
     └────────┬─────────┘                    │                           │
              ▼                              ▼                           │
        ┌─────────────────────────────────────────────┐                  │
        │              EVENT AI SUMMARY               │                  │
        │  Combines doc + video summaries into event  │                  │
        │  summary for each meeting                   │                  │
        └─────────────────────┬───────────────────────┘                  │
                              │                                          │
                              ▼                                          ▼
                 ┌─────────────────────────────────────────────────────────┐
                 │                 PERIODIC SUMMARIES                      │
                 │  Aggregates events into time-based summaries            │
                 │  ┌─────────┬─────────┬─────────┬─────────┬───────────┐ │
                 │  │  Daily  │ Weekly  │ Monthly │Quarterly│  Annual   │ │
                 │  └─────────┴─────────┴─────────┴─────────┴───────────┘ │
                 └─────────────────────────────────────────────────────────┘
```

## Two Parallel Processing Paths

### PDF Documents (Agendas, Minutes, Legislation)

| Stage | Status Values | Description |
|-------|---------------|-------------|
| **Discover** | `discovered` | Scraper found the URL, document record created |
| **Download** | `downloading` → `downloaded` | PDF file downloaded to local storage |
| **Extract** | `extracting` → `extracted` | Text extracted from PDF |
| **AI Summary** | `ai_pending` → `ai_processing` → `completed` | AI generates summary |

### Videos (YouTube, Vimeo)

| Stage | Status Values | Description |
|-------|---------------|-------------|
| **Discover** | `discovered` | Scraper found the video URL |
| **AI Transcribe** | `ai_pending` → `ai_processing` → `completed` | Direct to AI (no download needed) |

Videos skip the download and extraction steps because transcription happens via platform APIs (YouTube captions) or cloud transcription services.

## Content Status Values

| Status | Description |
|--------|-------------|
| `discovered` | URL found by scraper, waiting to be processed |
| `download_pending` | Queued for download |
| `downloading` | Currently being downloaded |
| `downloaded` | File downloaded successfully |
| `extraction_pending` | Queued for text extraction |
| `extracting` | Text currently being extracted |
| `extracted` | Text extraction complete |
| `ai_pending` | Queued for AI processing |
| `ai_processing` | AI currently processing |
| `completed` | Fully processed |
| `failed` | Processing failed (check `error_message`) |
| `skipped` | Intentionally skipped (duplicate, unsupported, etc.) |

## Database Tables

### `documents` Table
Stores all content items (PDFs, videos, legislation) with their processing status.

Key columns:
- `content_status` - Current position in pipeline
- `document_type` - Type of content (agenda, minutes, video, ordinance, resolution)
- `error_message` - Error details if failed
- `retry_count` - Number of retry attempts
- `discovered_at`, `download_completed_at`, `extraction_completed_at`, `ai_completed_at` - Timestamps

### `events` Table
Stores meetings/events. Each event can have multiple linked documents.

Key columns:
- `ai_summary` - Generated summary combining all linked document summaries

### `summaries` Table
Stores periodic summaries (daily, weekly, monthly, quarterly, annual).

Key columns:
- `summary_type` - Type of summary period
- `status` - `pending`, `generating`, `completed`, `failed`
- `period_start`, `period_end` - Time range covered

## Processing Priority & Dependencies

The AI queue processes items in **dependency order**:

### Tier 1: Documents & Videos (No Dependencies)
- Extracted PDFs ready for AI summary
- Videos ready for transcription
- Processed by date priority (future first, then most recent)

### Tier 2: Events (Depends on Documents)
- **Only processed when ALL linked documents have AI summaries**
- Events with unsummarized documents are "blocked"
- Must have at least one summarized document to be eligible

### Tier 3: Periodic Summaries (Depends on Events)
- **Only processed when events in the period have AI summaries**
- Daily/weekly/monthly summaries wait for event summaries
- Blocked summaries don't consume processing resources

### Within Each Tier
1. **Future dates first** - Upcoming meetings are highest priority
2. **Most recent past** - Recent historical content next
3. **Oldest last** - Historical backfill happens when queue is clear

## Queue API Endpoints

The admin dashboard exposes queue status via REST API:

### `GET /api/queue`
Returns overall queue status with counts for each stage.

Response includes:
- `download`, `extraction`, `ai_documents`, `ai_videos` - Counts for content pipeline
- `ai_events` - Includes `ready` (all docs summarized) and `blocked` (waiting on docs)
- `ai_summaries` - Includes `ready` (all events summarized) and `blocked` (waiting on events)
- `total_pending`, `total_in_progress` - Aggregate counts
- `is_healthy`, `health_message` - System health status

### `GET /api/queue/items?status=<status>&limit=<n>&offset=<n>`
Returns paginated list of items, optionally filtered by status.

## Monitoring

The admin dashboard at `/queue` provides:
- Pipeline overview with counts at each stage
- Items completed today
- Failed item counts
- Filterable list of all queue items
- Auto-refresh every 10 seconds

## Error Handling

- Failed items are marked with `content_status = 'failed'`
- `error_message` contains the failure reason
- `retry_count` tracks retry attempts
- Failed items can be retried via the queue maintenance job
