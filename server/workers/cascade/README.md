# /cascade

Background worker that orchestrates AI processing for Civic Commons.

## 🎯 Responsibilities

**This service IS responsible for:**
- ✅ Polling database for items needing AI analysis
- ✅ Calling MCP server endpoints to generate summaries
- ✅ Processing items in dependency order
- ✅ Tracking processed items via `cascade_triggered_at` column

**This service is NOT responsible for:**
- ❌ Running AI models directly (delegated to MCP)
- ❌ Downloading or extracting documents (handled by Scraper)

## Architecture

```
┌─────────────────┐
│     Cascade     │
│     Worker      │
└────────┬────────┘
         │
         │ Poll every 30s
         ▼
┌─────────────────┐     HTTP POST     ┌─────────────────┐
│   PostgreSQL    │◄─────────────────►│   MCP Server    │
│                 │                   │                 │
│ • Queue state   │                   │ • /summarize_*  │
│ • AI summaries  │                   │ • Gemini API    │
└─────────────────┘                   └─────────────────┘
```

## Processing Order

Items are processed in **date order (newest first) with cascading dependencies**:

```
For each date (newest first):
  1. Process all documents for that date
  2. Process all videos for that date
  3. Process event summary (requires doc/video summaries)
  4. Process daily summary (requires event summary)
Then move to previous date

After daily summaries complete for a period:
  5. Weekly summary (requires all daily summaries in that week)
  6. Monthly summary (requires all weekly summaries in that month)
  7. Quarterly summary (requires all monthly summaries in that quarter)
  8. Annual summary (requires all quarterly summaries in that year)
```

### Cascade Invalidation

When a **new document arrives for an old date**, all dependent summaries are invalidated and re-queued:

```
New document for Dec 9th arrives on Jan 3rd
  ↓
Dec 9th Event summary → marked stale, re-queued
  ↓
Dec 9th Daily summary → marked stale, re-queued
  ↓
Week 50 Weekly summary → marked stale, re-queued
  ↓
December Monthly summary → marked stale, re-queued
  ↓
Q4 Quarterly summary → marked stale, re-queued
  ↓
2024 Annual summary → marked stale, re-queued
```

This ensures summaries always reflect the latest data, even when documents arrive late (e.g., meeting minutes posted weeks after the meeting).

### Example Flow

Given data for Dec 9th and Dec 10th (end of week):

| Step | Date | Item | Why |
|------|------|------|-----|
| 1 | Dec 10 | Document: Packet.pdf | Newest date, documents first |
| 2 | Dec 10 | Document: Report.pdf | Same date, same priority |
| 3 | Dec 10 | Event: Planning Commission | All docs done for this date |
| 4 | Dec 10 | Daily Summary | Event done for this date |
| 5 | Dec 9 | Document: Agenda.pdf | Previous date begins |
| 6 | Dec 9 | Document: Minutes.pdf | Same date, same priority |
| 7 | Dec 9 | Video: Meeting Recording | Same date, same priority |
| 8 | Dec 9 | Event: City Council | All docs/videos done for this date |
| 9 | Dec 9 | Daily Summary | Event done for this date |
| 10 | Week 50 | Weekly Summary | All daily summaries for week complete |
| 11 | Dec 2024 | Monthly Summary | All weekly summaries for month complete |
| 12 | Q4 2024 | Quarterly Summary | All monthly summaries for quarter complete |
| 13 | 2024 | Annual Summary | All quarterly summaries for year complete |

### Late Document Example

Minutes for Dec 9th meeting arrive on Jan 3rd:

| Step | Action | Why |
|------|--------|-----|
| 1 | Process new Minutes document | New document, highest priority |
| 2 | Invalidate Dec 9th Event summary | New doc affects event |
| 3 | Invalidate Dec 9th Daily summary | Event changed |
| 4 | Invalidate Week 50 Weekly summary | Daily changed |
| 5 | Invalidate Dec 2024 Monthly summary | Weekly changed |
| 6 | Invalidate Q4 2024 Quarterly summary | Monthly changed |
| 7 | Invalidate 2024 Annual summary | Quarterly changed |
| 8 | Re-process all invalidated summaries in order | Cascade rebuilds |

### Priority Rules

| Priority | Item Type | Condition |
|----------|-----------|-----------|
| 1 | Documents & Videos | `ai_summary IS NULL` AND `content_status = 'ready'`, ordered by date DESC |
| 2 | Events | All linked docs/videos have summaries, ordered by date DESC |
| 3 | Daily Summaries | All events for that date have summaries |
| 4 | Weekly Summaries | All daily summaries in that week complete |
| 5 | Monthly Summaries | All weekly summaries in that month complete |
| 6 | Quarterly Summaries | All monthly summaries in that quarter complete |
| 7 | Annual Summaries | All quarterly summaries in that year complete |

## MCP Endpoints Called

| Endpoint | Purpose |
|----------|---------|
| `POST /summarize_document` | Generate summary from PDF content |
| `POST /summarize_video` | Generate summary from YouTube transcript |
| `POST /summarize_event` | Combine document summaries into event summary |
| `POST /generate_period_summary` | Generate newsletter/digest |

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | - | PostgreSQL connection string |
| `MCP_URL` | http://commons-mcp:8000 | MCP server URL |
| `LOG_LEVEL` | INFO | Logging level |
| `POLL_INTERVAL` | 30 | Seconds between queue checks |

## Docker

```bash
# Build and run
docker compose build commons-cascade
docker compose up -d commons-cascade

# View logs
docker compose logs -f commons-cascade

# Restart to pick up MCP changes
docker compose restart commons-cascade
```

## Monitoring

The cascade service logs its activities to:
1. **stdout** - Container logs via `docker logs`
2. **activity_log table** - Database with category='ai'

Check activity log:
```sql
SELECT timestamp, action, message 
FROM activity_log 
WHERE category = 'ai' 
ORDER BY timestamp DESC 
LIMIT 20;
```

## Error Handling

- Failed AI calls are logged but don't stop processing
- Items that fail are not retried immediately (will be picked up on next poll)
- MCP server unavailability results in 503 errors logged per item
