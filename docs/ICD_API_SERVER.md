# Interface Control Document: API Server

**Document Version:** 1.0  
**Date:** December 27, 2025  
**Service Name:** Civic Commons API Server  
**Service Port:** 8080  
**Protocol:** HTTP/REST + Server-Sent Events

---

## 1. Overview

The API Server is the HTTP gateway for Civic Commons, providing REST endpoints for the web frontend, chat with AI function calling, activity logging, and tool execution. It bridges the web UI and internal services.

### Key Responsibilities
- **Event Management**: CRUD operations on events
- **Document Management**: Upload, track, process documents
- **Summary Generation**: Trigger and retrieve period summaries
- **Chat Interface**: Conversational AI with function calling
- **Activity Logging**: Record all system operations
- **Tool Execution**: Execute tools with role-based access control

### Architecture Pattern
- **Stateless**: All state stored in PostgreSQL
- **Async/Await**: All I/O operations are non-blocking
- **Role-Based Access**: Permission checks on all endpoints
- **Centralized Logging**: All actions logged to activity_log table

---

## 2. Network Interfaces

### 2.1 Base URL
```
http://localhost:8080/
http://commons-api:8080/  (Docker internal)
```

### 2.2 REST Endpoints

#### Health & Status

**GET `/health`**
- **Purpose**: Service health check
- **Response**: `{"status": "healthy", "database": "connected"}`
- **Status**: 200

#### Events

**GET `/events`**
- **Purpose**: List all events for city
- **Query Parameters**:
  ```
  city_id=twinsburg_oh      (optional, default from config)
  start_date=2025-12-01     (optional, ISO date)
  end_date=2025-12-31       (optional, ISO date)
  category=meeting          (optional: meeting, community, etc)
  limit=100                 (optional, default 100)
  offset=0                  (optional, default 0)
  ```
- **Response**:
  ```json
  {
    "city_id": "twinsburg_oh",
    "total": 42,
    "events": [
      {
        "id": 1,
        "title": "City Council Meeting",
        "start_time": "2025-12-27T19:00:00Z",
        "end_time": "2025-12-27T21:00:00Z",
        "location": "City Hall",
        "category": "meeting",
        "description": "Monthly council meeting",
        "is_cancelled": false,
        "is_virtual": false,
        "virtual_url": null,
        "ai_summary": "Council approved budget...",
        "created_at": "2025-12-20T10:00:00Z",
        "updated_at": "2025-12-27T15:00:00Z"
      }
    ]
  }
  ```
- **Status**: 200

**GET `/events/{event_id}`**
- **Purpose**: Get single event details
- **Parameters**: `event_id` (path, integer)
- **Response**: Single event object (see above)
- **Status**: 200, 404 (not found)

**POST `/events`**
- **Purpose**: Create new event
- **Request Body**:
  ```json
  {
    "title": "City Council Meeting",
    "start_time": "2025-12-27T19:00:00",
    "end_time": "2025-12-27T21:00:00",
    "location": "City Hall",
    "category": "meeting",
    "description": "Monthly meeting",
    "is_virtual": false,
    "virtual_url": null,
    "source_id": 1,
    "external_id": "cc_2025_12_27"
  }
  ```
- **Response**: Created event object with `id`
- **Status**: 201 (created), 400 (validation error)
- **Permissions**: `write:events`

**PUT `/events/{event_id}`**
- **Purpose**: Update event
- **Parameters**: `event_id` (path)
- **Request Body**: Event fields to update
- **Response**: Updated event object
- **Status**: 200, 404, 400
- **Permissions**: `write:events`

**DELETE `/events/{event_id}`**
- **Purpose**: Delete event
- **Parameters**: `event_id` (path)
- **Response**: `{"success": true, "event_id": 1}`
- **Status**: 200, 404
- **Permissions**: `admin:events`

#### Documents

**GET `/documents`**
- **Purpose**: List documents
- **Query Parameters**:
  ```
  event_id=42              (optional, filter by event)
  status=discovered        (optional: discovered, downloading, processing, completed, failed)
  city_id=twinsburg_oh     (optional)
  limit=100
  offset=0
  ```
- **Response**:
  ```json
  {
    "total": 250,
    "documents": [
      {
        "id": 1,
        "title": "City Council Agenda - Dec 27",
        "document_type": "agenda",
        "status": "completed",
        "source_url": "https://example.com/agenda.pdf",
        "local_path": "/data/documents/cc_agenda_20251227.pdf",
        "text_extracted": "City Council Meeting Agenda...",
        "event_id": 42,
        "created_at": "2025-12-27T09:00:00Z",
        "downloaded_at": "2025-12-27T09:15:00Z",
        "extracted_at": "2025-12-27T09:30:00Z"
      }
    ]
  }
  ```
- **Status**: 200

**GET `/documents/{doc_id}`**
- **Purpose**: Get document details
- **Response**: Single document object
- **Status**: 200, 404

**POST `/documents/upload`**
- **Purpose**: Upload document file
- **Request**: Form data with file upload
- **Parameters**:
  ```
  file: <binary>
  title: "Document Title"
  event_id: 42 (optional)
  document_type: "minutes" (agenda, minutes, video, attachment, packet)
  ```
- **Response**: Created document object
- **Status**: 201, 400 (validation)
- **Permissions**: `write:documents`

**GET `/documents/{doc_id}/content`**
- **Purpose**: Get extracted text content
- **Response**: `{"content": "Full document text..."}`
- **Status**: 200, 404

#### Summaries

**GET `/summaries`**
- **Purpose**: List summaries
- **Query Parameters**:
  ```
  city_id=twinsburg_oh
  summary_type=weekly       (daily, weekly, monthly, quarterly, annual)
  status=published          (draft, published, archived)
  start_date=2025-12-01
  end_date=2025-12-31
  limit=50
  ```
- **Response**:
  ```json
  {
    "total": 12,
    "summaries": [
      {
        "id": 1,
        "title": "Weekly Summary - Dec 20-27",
        "summary_type": "weekly",
        "text": "This week saw 3 city council meetings...",
        "status": "published",
        "model": "gemini-2.5-flash",
        "period_start": "2025-12-20",
        "period_end": "2025-12-27",
        "generated_at": "2025-12-27T10:00:00Z",
        "created_at": "2025-12-27T10:00:00Z",
        "updated_at": "2025-12-27T10:00:00Z"
      }
    ]
  }
  ```
- **Status**: 200

**GET `/summaries/{summary_id}`**
- **Purpose**: Get summary details
- **Response**: Single summary object
- **Status**: 200, 404

**POST `/summaries/generate`**
- **Purpose**: Trigger summary generation
- **Request Body**:
  ```json
  {
    "summary_type": "weekly",
    "period_start": "2025-12-20",
    "period_end": "2025-12-27",
    "city_id": "twinsburg_oh"
  }
  ```
- **Response**: `{"summary_id": 42, "status": "generating", "queued_at": "..."}`
- **Status**: 202 (accepted), 400
- **Permissions**: `write:summaries`

#### Activity Logs

**GET `/logs`**
- **Purpose**: List activity logs
- **Query Parameters**:
  ```
  level=info                (info, success, warning, error)
  category=tool_call        (download, extraction, ai, scrape, system, event, linking, summary, tool_call)
  action=completed          (started, completed, failed, queued, etc)
  entity_type=event         (event, document, summary, source, tool)
  entity_id=42              (optional, filter by entity)
  start_date=2025-12-20
  end_date=2025-12-27
  limit=100
  ```
- **Response**:
  ```json
  {
    "total": 1250,
    "logs": [
      {
        "id": 1,
        "timestamp": "2025-12-27T15:30:00Z",
        "level": "success",
        "category": "tool_call",
        "action": "completed",
        "message": "✓ Created new event: City Council Meeting [Date: 2025-12-27T19:00:00, Location: City Hall]",
        "entity_type": "event",
        "entity_id": 42,
        "entity_title": "City Council Meeting",
        "source_name": "City Council RSS",
        "details": {
          "args": {"title": "City Council Meeting", "source_id": 1},
          "result": {"action": "create", "event_id": 42},
          "execution_time_ms": 125.5,
          "source": "mcp"
        }
      }
    ]
  }
  ```
- **Status**: 200

**POST `/internal/log`**
- **Purpose**: Record activity log (internal use)
- **Request Body**:
  ```json
  {
    "level": "success",
    "category": "tool_call",
    "action": "completed",
    "message": "Tool executed successfully",
    "entity_type": "event",
    "entity_id": 42,
    "entity_title": "Event Title",
    "source_name": "Source Name",
    "details": {}
  }
  ```
- **Response**: `{"id": 1, "created_at": "2025-12-27T15:30:00Z"}`
- **Status**: 201

#### Chat Interface

**POST `/chat`**
- **Purpose**: Send message to AI chat with function calling
- **Request Body**:
  ```json
  {
    "city_id": "twinsburg_oh",
    "messages": [
      {
        "role": "user",
        "content": "What happened at the last city council meeting?"
      }
    ],
    "tools": ["find_events", "search_documents", "get_summary"]
  }
  ```
- **Response**: Server-Sent Events stream
  ```
  event: message
  data: {"type": "thinking", "content": "..."}
  
  event: function_call
  data: {"tool": "find_events", "args": {...}}
  
  event: function_result
  data: {"tool": "find_events", "result": {...}}
  
  event: message
  data: {"type": "text", "content": "The last city council meeting..."}
  ```
- **Status**: 200 (stream)
- **Permissions**: `read:events`, `read:documents`

**POST `/chat/function_call`**
- **Purpose**: Execute function call from chat
- **Request Body**:
  ```json
  {
    "tool": "find_events",
    "args": {"start_date": "2025-12-20", "category": "meeting"}
  }
  ```
- **Response**: Tool-specific result
- **Status**: 200, 400, 500
- **Internal**: Used by chat interface

#### Sources

**GET `/sources`**
- **Purpose**: List data sources
- **Response**:
  ```json
  {
    "sources": [
      {
        "id": 1,
        "name": "City Council RSS",
        "driver_type": "civic_plus_rss",
        "is_enabled": true,
        "schedule": "0 6 * * *",
        "last_fetched_at": "2025-12-27T06:15:00Z",
        "last_success_at": "2025-12-27T06:15:00Z",
        "consecutive_failures": 0
      }
    ]
  }
  ```
- **Status**: 200

**POST `/sources/{source_id}/trigger`**
- **Purpose**: Manually trigger scrape for source
- **Parameters**: `source_id` (path)
- **Response**: `{"source_id": 1, "triggered_at": "2025-12-27T15:30:00Z"}`
- **Status**: 200
- **Permissions**: `admin:scraper`

### 2.3 Server-Sent Events (SSE)

**GET `/chat` (streaming)**
- **Purpose**: Stream chat responses
- **Headers**: `Content-Type: text/event-stream`
- **Events**:
  ```
  event: message          # Chat message chunk
  event: function_call    # Tool being called
  event: function_result  # Tool result received
  event: error           # Error occurred
  ```

---

## 3. Data Models

### 3.1 Event Model
```python
{
    "id": int,
    "title": str,
    "description": str | None,
    "start_time": datetime,
    "end_time": datetime | None,
    "location": str | None,
    "category": str,  # meeting, community, recreation, etc
    "is_cancelled": bool,
    "is_virtual": bool,
    "virtual_url": str | None,
    "ai_summary": str | None,
    "ai_summary_updated_at": datetime | None,
    "ai_model_used": str | None,
    "created_at": datetime,
    "updated_at": datetime
}
```

### 3.2 Document Model
```python
{
    "id": int,
    "title": str,
    "document_type": str,  # agenda, minutes, video, attachment, packet
    "status": str,  # discovered, downloading, processing, completed, failed
    "source_url": str | None,
    "local_path": str | None,
    "text_extracted": str | None,
    "event_id": int | None,
    "created_at": datetime,
    "downloaded_at": datetime | None,
    "extracted_at": datetime | None
}
```

### 3.3 Summary Model
```python
{
    "id": int,
    "title": str,
    "summary_type": str,  # daily, weekly, monthly, quarterly, annual
    "text": str,
    "status": str,  # draft, published, archived
    "model": str,  # gemini model used
    "period_start": date,
    "period_end": date,
    "generated_at": datetime,
    "created_at": datetime,
    "updated_at": datetime
}
```

### 3.4 Activity Log Model
```python
{
    "id": int,
    "timestamp": datetime,
    "level": str,  # info, success, warning, error
    "category": str,  # download, extraction, ai, scrape, system, etc
    "action": str,  # started, completed, failed, queued, etc
    "message": str,  # Human-readable message
    "entity_type": str | None,  # event, document, summary, etc
    "entity_id": int | None,
    "entity_title": str | None,
    "source_name": str | None,
    "details": dict  # Tool-specific details
}
```

### 3.5 Chat Message Model
```python
{
    "role": str,  # "user" | "assistant" | "tool"
    "content": str,  # Message text
    "tool_name": str | None,  # If role == "tool"
    "tool_args": dict | None
}
```

---

## 4. Data Flow Diagrams

### 4.1 Event Retrieval Flow
```
GET /events
    ↓
Validate city_id, date range
    ↓
Query events table with filters
    ↓
Return event list with summaries
    ↓
Client renders timeline/list
```

### 4.2 Document Processing Flow
```
POST /documents/upload
    ↓
Store file to disk
    ↓
Create document record (status: discovered)
    ↓
Queue for download/extraction
    ↓
Activity log: "Download started"
    ↓
Extraction service processes
    ↓
Activity log: "Extraction completed"
    ↓
Update document.text_extracted
    ↓
Trigger MCP linking (if event linked)
    ↓
Activity log: "Document linked to event #42"
```

### 4.3 Chat with Tools Flow
```
POST /chat (streaming)
    ↓
Send to Gemini with function definitions
    ↓
Stream thinking/response back
    ↓
If function call needed:
    ├─ Send function_call event
    ├─ Client prepares result
    ├─ POST /chat/function_call
    └─ Send function_result event
    ↓
Continue streaming until done
    ↓
Send final message event
```

---

## 5. Authentication & Authorization

### 5.1 Current (Development)
- **No authentication** on endpoints
- All operations allow public access

### 5.2 Future (Production)
- **JWT Tokens**: Bearer token in Authorization header
- **Scopes**:
  - `read:events` - View events
  - `read:documents` - View documents
  - `read:summaries` - View summaries
  - `write:events` - Create/edit events
  - `write:documents` - Upload documents
  - `write:summaries` - Trigger summary generation
  - `admin:scraper` - Trigger scraper manually
  - `admin:events` - Delete events

### 5.3 Rate Limiting (Future)
- 100 requests/minute per API key
- 10 concurrent requests per client
- Tool execution: 30 second timeout

---

## 6. Error Handling

### 6.1 HTTP Status Codes
| Code | Meaning | Example |
|------|---------|---------|
| 200 | Success | Event retrieved |
| 201 | Created | Event created |
| 202 | Accepted | Summary generation queued |
| 400 | Bad Request | Invalid parameters |
| 404 | Not Found | Event doesn't exist |
| 422 | Validation Error | Invalid event data |
| 500 | Server Error | Database error |
| 503 | Unavailable | Database down |

### 6.2 Error Response Format
```json
{
    "detail": "Error message",
    "status_code": 400,
    "timestamp": "2025-12-27T10:00:00Z",
    "request_id": "req_12345"
}
```

### 6.3 Validation Error Response
```json
{
    "detail": [
        {
            "loc": ["body", "title"],
            "msg": "field required",
            "type": "value_error.missing"
        }
    ]
}
```

---

## 7. Performance Specifications

### 7.1 Latency Targets
| Operation | Target | Notes |
|-----------|--------|-------|
| GET /events | < 200ms | With 1000 events |
| POST /events | < 100ms | Single event creation |
| GET /documents | < 300ms | With pagination |
| POST /chat | < 5s | First message (Gemini call) |
| Function call | < 3s | Query execution |

### 7.2 Throughput
- **Concurrent Users**: 50+ simultaneous chat sessions
- **API Requests**: 100+ requests/second
- **Database Queries**: 1000+ per second

### 7.3 Database Pooling
- **Pool Size**: 20-30 connections
- **Queue Size**: 200+ pending
- **Statement Cache**: 100 prepared statements

---

## 8. Configuration

### 8.1 Environment Variables
```bash
DATABASE_URL=postgresql://user:pass@localhost/civic_commons
GEMINI_API_KEY=your-api-key         # Optional
MCP_URL=http://localhost:8000       # MCP server URL
API_CORS_ORIGINS=http://localhost:3000,http://localhost:3002
INTERNAL_API_URL=http://commons-api:8080  # Internal HTTP URL
```

### 8.2 Settings
```python
{
    "database_url": "postgresql://...",
    "pool_size": 20,
    "cors_origins": ["http://localhost:3000"],
    "chat_timeout": 60,
    "sse_timeout": 30,
}
```

---

## 9. Testing

### 9.1 Manual Testing
```bash
# Get events
curl http://localhost:8080/events?start_date=2025-12-01

# Create event
curl -X POST http://localhost:8080/events \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test Event",
    "start_time": "2025-12-27T19:00:00",
    "location": "City Hall"
  }'

# Get activity logs
curl http://localhost:8080/logs?category=tool_call&limit=10

# Chat
curl -N http://localhost:8080/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What events happened?"}],
    "tools": ["find_events"]
  }'
```

### 9.2 Integration Tests
- CRUD operations on events
- Document upload and extraction
- Chat with multiple tool calls
- Concurrent requests and connection pooling
- Error handling and validation

---

## 10. Monitoring & Observability

### 10.1 Health Checks
```bash
# Basic health
curl http://localhost:8080/health

# Readiness (database connection)
curl http://localhost:8080/health  # Includes DB check
```

### 10.2 Metrics (Future)
- Request latency histogram
- Database query count/duration
- Chat API call count
- Active SSE connections
- Error rate by endpoint

### 10.3 Logging
```json
{
    "timestamp": "2025-12-27T10:00:00Z",
    "level": "INFO",
    "service": "civic_commons.api",
    "endpoint": "GET /events",
    "status": 200,
    "duration_ms": 145,
    "city_id": "twinsburg_oh",
    "user_id": null
}
```

---

## 11. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-27 | Initial ICD: REST endpoints, chat, activity logging |

---

## 12. Contact & Support

**Primary Contact**: Development Team  
**Documentation**: `/docs/ICD_API_SERVER.md`  
**Code**: `/server/api_server.py`  
**Issues**: GitHub Issues tracker  
**Chat**: Check `/server/chat.py`

---

## Appendix A: Common Request Examples

### Create Event from Chat
```json
POST /events
{
  "title": "City Council Meeting",
  "start_time": "2025-12-27T19:00:00",
  "end_time": "2025-12-27T21:00:00",
  "location": "City Hall Chambers",
  "category": "meeting",
  "description": "Regular monthly council meeting",
  "is_virtual": false,
  "source_id": 1,
  "external_id": "cc_20251227"
}
```

### Query Events for Date Range
```
GET /events?start_date=2025-12-20&end_date=2025-12-27&category=meeting&limit=50
```

### Generate Weekly Summary
```json
POST /summaries/generate
{
  "summary_type": "weekly",
  "period_start": "2025-12-20",
  "period_end": "2025-12-27",
  "city_id": "twinsburg_oh"
}
```

### Chat with Event Search
```json
POST /chat
{
  "city_id": "twinsburg_oh",
  "messages": [
    {"role": "user", "content": "List all city council meetings this month"}
  ],
  "tools": ["find_events", "get_summary"]
}
```
