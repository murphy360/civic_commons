# Phase 1: MCP Event Analysis Tool - Implementation Summary

## Overview
Completed Phase 1 of the scraper refactoring to enable MCP-driven event deduplication. The system now provides AI-powered event analysis via MCP that the scraper implements.

## Architecture

### Design Principle
- **MCP Server**: Provides intelligent decision-making (read-only)
- **Scraper**: Implements decisions (with write access)
- **Decision Path**: Single, unified flow for all events

### Key Components

#### 1. `server/event_tools.py` (Decision Logic)
- **Function**: `analyze_event_for_upsert()`
- **Purpose**: Analyze event and recommend action
- **Returns**: `{action, event_id, confidence, reasoning, error}`
- **Actions**:
  - `"create"` - Create new event
  - `"merge"` - Merge with existing event_id
  - `"error"` - Analysis failed

**Decision Path**:
1. Check exact `external_id` match → return `merge` (confidence 1.0)
2. Find similar events by title/date (±4 hours)
3. If similar found and AI processor available:
   - Call AI to verify duplication
   - If AI confirms → return `merge` (with confidence)
4. If no match → return `create`

**Helper Functions**:
- `_check_external_id_match()` - Fast path lookup
- `_find_similar_events()` - Title similarity + date window search
- `_verify_with_ai()` - AI-powered duplicate verification
- `_parse_iso_datetime()` - ISO format parsing

#### 2. `server/mcp_event_tools.py` (MCP Registration)
- **Function**: `register_event_tools()`
- **Purpose**: Expose decision logic as MCP tool
- **Exposes**: `analyze_event_for_upsert_tool` via FastMCP

#### 3. `server/main.py` (Integration)
- **Change**: Imports `register_event_tools` from `mcp_event_tools`
- **Change**: Calls `register_event_tools(mcp, db)` in `register_unified_tools()`
- **Result**: MCP server now exposes the event analysis tool

### Database Access
- Uses **server/db.py** Database class (read-only)
- Queries via asyncpg connection pool
- No write operations (decisions only)

### AI Integration
- Accepts optional `AIEventProcessor` instance
- Used for `evaluate_event_match()` calls
- Optional: Tool works without AI (returns "create" for similar events)

## Scraper Integration (Next Phase)

### Phase 2: Scraper Worker Updates
When scraper calls the MCP tool:

```python
# In scraper worker
response = await mcp_client.call_tool(
    "analyze_event_for_upsert_tool",
    source_id=123,
    title="Tech Meetup",
    start_time="2024-01-15T19:00:00",
    location="Downtown",
    external_id="evt_456",
)

# Response example:
# {
#     "action": "merge",
#     "event_id": 42,
#     "confidence": 0.95,
#     "reasoning": "Exact external_id match: evt_456",
#     "error": null
# }

if response["action"] == "create":
    await db_pool.create_event(...)
elif response["action"] == "merge":
    await db_pool.merge_events(response["event_id"], ...)
```

## Code Structure

### Files Modified
1. **server/event_tools.py** - Complete rewrite
   - Changed from action-based to decision-based
   - Now read-only with external dependencies
   - 250 lines, 6 functions

2. **server/mcp_event_tools.py** - Created
   - Registers event analysis tool with MCP
   - ~85 lines, clean separation of concerns

3. **server/main.py** - Minor update
   - Added import: `from mcp_event_tools import register_event_tools`
   - Added call: `register_event_tools(mcp, db, ai_processor=None)`

4. **server/tool_registry.py** - No changes
   - Not needed (event tool registered directly via mcp_event_tools)
   - Could add for future documentation

### Testing Status
✅ Syntax validation - All files pass Python 3.11 syntax checks
⚠️ Import validation - mcp module import shows expected runtime dependency
⏳ Runtime testing - Awaits scraper Phase 2 integration

## Key Decisions

### Why Not Use tool_registry?
- Event tool has special dependencies (Database, AIEventProcessor)
- Direct registration via `register_event_tools()` is cleaner
- Follows pattern of `register_admin_tools()`

### Why Decision-Based, Not Action-Based?
- MCP server has read-only database access
- Scraper has write database access
- Separation of concerns: analyze vs. implement
- Simpler to test and reason about

### Why No "update" Action?
- External ID match automatically implies update
- No need for separate action type
- Simpler decision tree

## Next Steps (Phase 2)

### Scraper Worker Integration (3-4 hours)
1. Update `scraper/main.py` to pass MCP client through components
2. Modify `scraper/pipeline/scraper.py` to call MCP instead of local dedup
3. Implement decision handler in storage layer
4. Add fallback: if MCP unavailable, use direct DB

### Document Linker Integration (2-3 hours)
1. Update `scraper/pipeline/document_linker.py` for MCP event creation
2. Keep document-to-event linking as DB operation (for now)

### Testing & Validation (3-4 hours)
1. Integration tests for MCP + DB fallback paths
2. Performance validation
3. Error scenario testing

## Monitoring & Logging

### Log Points
- `civic_commons.event_tools` - Decision logic
- `civic_commons.mcp` - MCP server lifecycle

### Expected Behavior
- Fast path (external_id): < 10ms
- Similar search: 50-200ms (depends on event count)
- AI verification: 1-5s (external API call)

## Error Handling

### Exception Scenarios
1. **Database error**: Returns `{"action": "error", "error": str(e)}`
2. **AI service down**: Falls back to create (if no exact match)
3. **Invalid datetime**: Uses current time as fallback
4. **Missing event data**: Graceful degradation with available info

## Future Enhancements

1. **Caching**: Cache AI decisions for identical event signatures
2. **Batch Analysis**: Accept multiple events for parallel processing
3. **Confidence Threshold**: Configurable merge threshold
4. **Audit Trail**: Log all MCP decisions for analysis
5. **Weights**: Configurable similarity weights (title, date, location)

---

**Status**: Phase 1 Complete ✅  
**Phase 2 Start**: Scraper worker integration  
**Estimated Total Time**: 15-18 hours  
