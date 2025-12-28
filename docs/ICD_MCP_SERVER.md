# Interface Control Document: MCP Server

**Document Version:** 1.0  
**Date:** December 27, 2025  
**Service Name:** Civic Commons MCP Server  
**Service Port:** 8000  
**Transport:** HTTP/SSE + WebSocket

---

## 1. Overview

The MCP (Model Context Protocol) Server is the centralized intelligence layer for Civic Commons. It provides unified tool execution, event analysis, document linking, and AI-powered processing for the entire system.

### Key Responsibilities
- **Event Deduplication**: Analyze incoming events and recommend create/merge actions
- **Document Linking**: Match documents to relevant events using AI
- **Cascade Triggering**: Initiate document analysis workflows
- **Summary Generation**: Create period summaries (daily, weekly, monthly, quarterly, annual)
- **Activity Logging**: Log all tool executions for audit trails

### Architecture Pattern
- **Dual Transport**: SSE for browser/external clients + FastMCP for internal stdio
- **Async Processing**: All operations are fully asynchronous
- **Connection Management**: Persistent SSE connections for streaming responses
- **Error Handling**: Graceful degradation when AI services unavailable

---

## 2. Network Interfaces

### 2.1 HTTP Endpoints

#### Connection Management

**POST `/connect`**
- **Purpose**: Establish new SSE connection
- **Request Body**: None
- **Response**: `{"connection_id": "uuid"}`
- **Status Codes**: 200 (success)
- **Example**:
  ```bash
  curl -X POST http://localhost:8000/connect
  # Returns: {"connection_id": "f0aaf355-ae61-4b09-8cd4-42a7c47d1886"}
  ```

**DELETE `/disconnect/{connection_id}`**
- **Purpose**: Close SSE connection
- **Parameters**: `connection_id` (path)
- **Response**: `{"status": "disconnected"}`
- **Status Codes**: 200, 404

**GET `/events`**
- **Purpose**: Stream SSE messages for connection
- **Parameters**: `connection_id` (query)
- **Response**: Server-Sent Events stream
- **Headers**: `Content-Type: text/event-stream`
- **Events**:
  - `keepalive`: {"} (every 30s)
  - `tool_result`: {"tool": "name", "result": {...}}
  - `message`: {"text": "..."}

#### Tool Execution

**POST `/call/{connection_id}/{tool_name}`**
- **Purpose**: Execute a tool and stream results
- **Parameters**:
  - `connection_id` (path): SSE connection ID
  - `tool_name` (path): Name of tool to execute
- **Request Body**: Tool-specific arguments (JSON)
- **Response**: 
  - Special tools (analyze_event_for_upsert): Full decision object
  - Other tools: `{"status": "success", "tool": "name"}`
- **Status Codes**: 200 (success), 404 (not found), 500 (error)

**Special Tool: `upsert_event`**
- **Description**: Create or merge event with deduplication (write-internal access)
- **Arguments**:
  ```json
  {
    "source_id": 1,
    "title": "City Council Meeting",
    "start_time": "2025-12-27T19:00:00",
    "location": "City Hall",
    "description": "Monthly meeting",
    "end_time": "2025-12-27T21:00:00",
    "category": "meeting",
    "is_virtual": false,
    "virtual_url": null,
    "external_id": "cc_2025_12_27",
    "source_url": "https://example.com/meeting"
  }
  ```
- **Response**:
  ```json
  {
    "action": "create|merge|error",
    "event_id": 42,
    "confidence": 0.95,
    "reasoning": "Exact external_id match to existing event",
    "error": null
  }
  ```
- **Decision Actions**:
  - `create`: Event is new, will be created
  - `merge`: Event matches existing (event_id provided), source will be added
  - `error`: Analysis failed, error message provided

#### Health & Status

**GET `/health`**
- **Purpose**: Service health check
- **Response**: `{"status": "healthy"}`
- **Status Codes**: 200

**GET `/tools`**
- **Purpose**: List available tools
- **Response**: Array of tool definitions with names, descriptions, parameters
- **Status Codes**: 200

---

## 3. Data Models

### 3.1 Event Decision Model
```python
{
    "action": str,           # "create" | "merge" | "error"
    "event_id": int | None,  # ID if merge action
    "confidence": float,     # 0.0-1.0 for merge confidence
    "reasoning": str,        # Why this decision was made
    "error": str | None      # Error message if action is "error"
}
```

### 3.2 Tool Result Model
```python
{
    "tool": str,            # Tool name
    "status": str,          # "success" | "error"
    "result": Any,          # Tool-specific output
    "execution_time_ms": float
}
```

### 3.3 SSE Message Format
```
event: <event_type>
data: <json_payload>

# Example:
event: tool_result
data: {"tool": "analyze_event_for_upsert_tool", "result": {"action": "create", ...}}
```

---

## 4. Tool Specifications

### 4.1 Event Tools

#### `upsert_event` (Write-Internal)
- **Registry Name**: `upsert_event`
- **Module**: `tool_registry.py` → calls `tools.upsert_event`
- **Purpose**: Create new event OR merge with existing using AI-powered deduplication
- **Deduplication Strategy**:
  1. Check `source_id` + `external_id` exact match (highest priority) → MERGE
  2. Query similar events by title/date using trigram similarity
  3. Use AI to verify potential duplicates (if confidence < threshold)
  4. If match ≥ 0.65 confidence → MERGE with existing
  5. Else → CREATE new event
- **Return**: Event decision object with action, event_id, confidence, reasoning
- **Access Level**: `write_internal` (scraper only)
- **Arguments**:
  ```json
  {
    "source_id": 1,
    "title": "City Council Meeting",
    "start_time": "2025-12-27T19:00",
    "location": "City Hall",
    "external_id": "cc_20251227",
    "description": "Monthly meeting",
    "end_time": "2025-12-27T21:00",
    "category": "meeting",
    "is_virtual": false,
    "virtual_url": null,
    "source_url": "https://..."
  }
  ```

#### `create_event` (Write-Internal)
- **Registry Name**: `create_event`
- **Purpose**: Direct event creation (bypasses deduplication)
- **Use Case**: Manual event entry, admin operations
- **Access Level**: `write_internal`
- **Note**: Usually `upsert_event` is preferred for data pipelines

#### `update_event` (Write-Internal)
- **Registry Name**: `update_event`
- **Purpose**: Update existing event details
- **Updatable Fields**: title, description, location, ai_summary
- **Access Level**: `write_internal`

### 4.2 Document Tools

#### `search_documents` (Read-Only)
- **Registry Name**: `search_documents`
- **Purpose**: Full-text search of meeting minutes, agendas, and documents
- **Search Fields**: Title, content, source type
- **Access Level**: `read_only` (safe for chat)
- **Arguments**:
  ```json
  {
    "city_id": "twinsburg",
    "query": "zoning change",
    "source_type": "city_council",
    "limit": 10
  }
  ```

#### `get_document_content` (Read-Only)
- **Registry Name**: `get_document_content`
- **Purpose**: Retrieve full text of specific document
- **Use Case**: After search, fetch document details
- **Access Level**: `read_only`

### 4.3 Query Tools (Read-Only)

#### `get_events` (Read-Only)
- **Registry Name**: `get_events`
- **Purpose**: Search for upcoming or past events and meetings
- **Filters**: Date range, source name, category
- **Access Level**: `read_only` (for chat)
- **Arguments**:
  ```json
  {
    "city_id": "twinsburg",
    "start_date": "2025-12-20",
    "end_date": "2025-12-31",
    "source_name": "City Council",
    "limit": 20
  }
  ```

#### `search_commons_records` (Read-Only)
- **Registry Name**: `search_commons_records`
- **Purpose**: Search community documents and records by keyword
- **Includes**: Content search with optional full text
- **Access Level**: `read_only`

#### `find_legislation` (Read-Only)
- **Registry Name**: `find_legislation`
- **Purpose**: Search legislation (ordinances, resolutions, motions)
- **Search By**: Type, number, or title text
- **Access Level**: `read_only`

#### `get_assistant_manifest` (Read-Only)
- **Registry Name**: `get_assistant_manifest`
- **Purpose**: Get assistant configuration (name, persona, city info)
- **Access Level**: `read_only`

#### `get_source_health` (Read-Only)
- **Registry Name**: `get_source_health`
- **Purpose**: Health status of data sources (freshness, availability)
- **Access Level**: `read_only`

### 4.4 Helper Tools (Write-Internal)

#### `add_source_to_event` (Write-Internal)
- **Registry Name**: `add_source_to_event`
- **Purpose**: Link a data source to existing event
- **Use Case**: When `upsert_event` merges, link the new source
- **Access Level**: `write_internal`

#### `link_document_to_event` (Write-Internal)
- **Registry Name**: `link_document_to_event`
- **Purpose**: Associate document (agenda/minutes) with event
- **Relationships**: agenda, minutes, summary, attachment, packet
- **Access Level**: `write_internal`

#### `validate_event` (Write-Internal)
- **Registry Name**: `validate_event`
- **Purpose**: Validate event quality and completeness
- **Checks**: Required fields, date format, location validity
- **Access Level**: `write_internal`

#### `find_duplicate_events` (Write-Internal)
- **Registry Name**: `find_duplicate_events`
- **Purpose**: Find events matching by similarity (used internally by upsert_event)
- **Threshold**: Configurable 0.0-1.0 for similarity
- **Access Level**: `write_internal`

#### `enrich_event_data` (Write-Internal)
- **Registry Name**: `enrich_event_data`
- **Purpose**: Add AI-generated metadata (summary, topics, sentiment)
- **Metadata**: ai_summary, key_topics, sentiment, importance_score
- **Access Level**: `write_internal`

---

## 5. Data Flow Diagrams

### 5.1 Event Processing Flow
```
Scraper discovers events
    ↓
POST /call/{conn_id}/upsert_event
    ↓
MCP Server (upsert_event handler)
├─ Check source_id + external_id exact match
├─ Query similar events by title/date (trigram)
└─ If similarity ≥ 0.65: Use AI to verify duplicate
    ↓
Returns decision: {action, event_id, confidence, reasoning}
├─ action: "create" → Create new event
├─ action: "merge" → Add source to existing event (event_id)
└─ action: "error" → Log failure, skip event
    ↓
Scraper implements decision:
├─ If "create": INSERT new event record
└─ If "merge": POST /call/{}/add_source_to_event
    ↓
Activity log captured: 
├─ "✓ Created event: {title} [Date: ..., Location: ...]"
└─ "⟷ Merged into event #{id}: {title} (confidence: 95%)"
```

### 5.2 Document Linking Flow
```
Document added to processing queue
    ↓
Text extraction (PDF, web content)
    ↓
Query database for related events
├─ By date proximity
└─ By title/content similarity
    ↓
Link document to matched events
├─ POST /call/{}/link_document_to_event
└─ Relationship type: agenda, minutes, etc
    ↓
If event has documents → trigger summary generation
    ↓
Summary added to database
    ↓
Admin UI shows: Documents → Summary
```

---

## 6. Connection Lifecycle

### 6.1 SSE Connection States

```
DISCONNECTED
    │
    ├─ POST /connect → CONNECTED (new connection_id issued)
    │
    └─ → CONNECTED
         │
         ├─ GET /events → Streaming (keepalives every 30s)
         │
         ├─ POST /call/{id}/{tool} → Tool executes, sends tool_result via SSE
         │
         └─ DELETE /disconnect/{id} → DISCONNECTED
```

### 6.2 Connection Timeout Behavior
- **Idle Timeout**: 30 seconds (keepalive sent to prevent timeout)
- **Tool Timeout**: 30 seconds per tool execution
- **Stream Timeout**: Connection closes if client disconnects or network fails
- **Reconnection**: Client must create new connection (different connection_id)

---

## 7. Error Handling

### 7.1 HTTP Status Codes
| Code | Meaning | Example |
|------|---------|---------|
| 200 | Success | Tool executed, result returned |
| 400 | Bad Request | Invalid tool arguments |
| 404 | Not Found | Invalid connection_id or tool_name |
| 500 | Internal Error | Database error, AI API failure |
| 503 | Service Unavailable | Database unavailable |

### 7.2 Error Response Format
```json
{
    "detail": "Error message describing what went wrong",
    "status_code": 500,
    "timestamp": "2025-12-27T10:00:00Z"
}
```

### 7.3 Tool Execution Error Handling
```python
# If tool fails, returns:
{
    "action": "error",
    "event_id": null,
    "confidence": null,
    "reasoning": "Error occurred",
    "error": "Specific error message"
}
```

---

## 8. Performance Specifications

### 8.1 Latency Targets
| Operation | Target | Notes |
|-----------|--------|-------|
| analyze_event_for_upsert | < 2s | Fast deduplication check |
| AI duplicate verify | < 5s | Gemini API call |
| generate_period_summary | < 10s | AI summarization |
| find_related_events | < 3s | Document linking |

### 8.2 Throughput
- **Concurrent Connections**: 100+ SSE clients
- **Tool Calls/Second**: 10+ per core
- **Event Processing**: 1000+ events/hour

### 8.3 Database Pooling
- **Pool Size**: 10-20 connections
- **Queue Size**: 100+ pending requests
- **Connection Timeout**: 30 seconds

---

## 9. Dependencies

### 9.1 External Services
| Service | Required | Purpose |
|---------|----------|---------|
| PostgreSQL | ✓ | Event data, documents, activity logs |
| Google Gemini API | ✗ | AI duplicate detection, summarization |
| Cascade Service | ✓ | Document processing trigger |

### 9.2 Internal Services
| Service | Port | Purpose |
|---------|------|---------|
| API Server | 8080 | Activity logging, tool execution |
| Scraper | N/A | Event source, triggering MCP |
| Admin UI | 3003 | Display logs, trigger scrapes |

---

## 10. Security Considerations

### 10.1 Authentication
- Currently: No authentication on local endpoints
- Future: JWT tokens for external access
- Internal: Firewall-protected Docker network

### 10.2 Data Validation
- All input validated using Pydantic models
- Tool arguments type-checked before execution
- Database queries use parameterized statements

### 10.3 Rate Limiting
- Per-connection rate limiting (future)
- Tool execution timeout: 30 seconds
- Connection idle cleanup: 60 seconds

---

## 11. Configuration

### 11.1 Environment Variables
```bash
DATABASE_URL=postgresql://user:pass@localhost/civic_commons
GEMINI_API_KEY=your-api-key          # Optional
GOOGLE_AI_API_KEY=your-api-key       # Optional
MCP_PORT=8000                         # Default port
```

### 11.2 Settings
```python
{
    "database_url": "postgresql://...",
    "pool_size": 20,
    "ai_enabled": true,
    "sse_timeout": 30,
    "tool_timeout": 30,
}
```

---

## 12. Logging

### 12.1 Log Levels
- **DEBUG**: SSE connection/disconnection, keepalives
- **INFO**: Tool execution start/end, connection events
- **WARNING**: Tool timeouts, AI API failures
- **ERROR**: Database errors, unhandled exceptions

### 12.2 Structured Logging
```json
{
    "timestamp": "2025-12-27T10:00:00Z",
    "level": "INFO",
    "service": "civic_commons.mcp",
    "message": "Tool executed",
    "tool_name": "analyze_event_for_upsert_tool",
    "duration_ms": 125,
    "status": "success",
    "connection_id": "f0aaf355..."
}
```

---

## 13. Testing

### 13.1 Manual Testing
```bash
# Connect
curl -X POST http://localhost:8000/connect
# Returns: {"connection_id": "abc123"}

# Execute tool
curl -X POST http://localhost:8000/call/abc123/analyze_event_for_upsert_tool \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": 1,
    "title": "Test Event",
    "start_time": "2025-12-27T19:00:00",
    "location": "City Hall"
  }'

# Disconnect
curl -X DELETE http://localhost:8000/disconnect/abc123
```

### 13.2 Integration Tests
- Event deduplication with various similarity levels
- SSE stream continuity over 10+ minute connections
- Tool timeout handling
- Concurrent tool execution
- Database pool exhaustion recovery

---

## 14. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-27 | Initial ICD: SSE transport, event analysis, document linking |

---

## 15. Contact & Support

**Primary Contact**: Development Team  
**Documentation**: `/docs/ICD_MCP_SERVER.md`  
**Code**: `/server/services/mcp/sse_server.py`  
**Issues**: GitHub Issues tracker
