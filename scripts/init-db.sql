-- Civic Commons Database Schema
-- Automatically runs on first container start via docker-entrypoint-initdb.d

-- Ensure the application role exists (safe to run multiple times)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'civic_commons') THEN
        CREATE ROLE civic_commons WITH LOGIN PASSWORD 'civic_commons';
    END IF;
END
$$;

-- =============================================================================
-- Extensions
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================================================
-- Helper Functions (must be defined before triggers that use them)
-- =============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- =============================================================================
-- Custom Types
-- =============================================================================

-- Legislation action types (for tracking legislative history)
CREATE TYPE legislation_action AS ENUM (
    'introduced',        -- First time legislation appears
    'first_reading',     -- First reading (required before vote)
    'second_reading',    -- Second reading (often final before vote)
    'third_reading',     -- Third reading (if required)
    'public_hearing',    -- Public hearing scheduled/held
    'amended',           -- Legislation was amended
    'tabled',            -- Postponed for future consideration
    'referred',          -- Referred to committee
    'approved',          -- Passed/adopted by council
    'adopted',           -- Formally adopted (similar to approved)
    'failed',            -- Did not pass
    'vetoed',            -- Vetoed by executive
    'withdrawn',         -- Withdrawn by sponsor
    'discussed'          -- General discussion (no specific action)
);

-- Legislation status (for tracking current state)
CREATE TYPE legislation_status AS ENUM (
    'proposed',          -- Initially proposed
    'first_reading',     -- After first reading
    'second_reading',    -- After second reading  
    'third_reading',     -- After third reading (if applicable)
    'approved',          -- Passed/adopted
    'failed',            -- Did not pass
    'vetoed',            -- Vetoed
    'withdrawn',         -- Withdrawn
    'tabled'             -- Tabled indefinitely
);

-- =============================================================================
-- City Configuration
-- =============================================================================
CREATE TABLE IF NOT EXISTS cities (
    id SERIAL PRIMARY KEY,
    city_id VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(256) NOT NULL,
    assistant_name VARCHAR(128),
    assistant_persona TEXT,
    timezone VARCHAR(64),  -- Should come from config
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS cities_city_id_idx ON cities(city_id);

-- =============================================================================
-- Entities (organizational units within a city)
-- =============================================================================
CREATE TABLE IF NOT EXISTS entities (
    id SERIAL PRIMARY KEY,
    city_id VARCHAR(64) NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    entity_key VARCHAR(64) NOT NULL,   -- Unique key within city (e.g., "city_council")
    display_name VARCHAR(256) NOT NULL, -- Human-readable name
    short_name VARCHAR(64),             -- Abbreviated name for UI
    domain VARCHAR(64),                 -- Category (civic, education, community, recreation, business)
    entity_type VARCHAR(64),            -- Type (department, board, commission, etc.)
    parent_entity_key VARCHAR(64),      -- Parent entity key (for hierarchy)
    parent_entity_id INTEGER,           -- Parent entity database ID (set after all entities created)
    aliases TEXT[],                     -- Alternative names for matching
    icon VARCHAR(64),                   -- Optional icon identifier
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL,
    UNIQUE(city_id, entity_key)
);

CREATE INDEX IF NOT EXISTS entities_city_id_idx ON entities(city_id);
CREATE INDEX IF NOT EXISTS entities_domain_idx ON entities(domain);
CREATE INDEX IF NOT EXISTS entities_parent_idx ON entities(parent_entity_id);

COMMENT ON TABLE entities IS 'Organizational units within a city (departments, boards, commissions)';
COMMENT ON COLUMN entities.domain IS 'Category: civic, education, community, recreation, business';
COMMENT ON COLUMN entities.entity_type IS 'Type: department, board, commission, committee, district';

-- =============================================================================
-- Color Schemes (visual styling for entity domains)
-- =============================================================================
CREATE TABLE IF NOT EXISTS color_schemes (
    id SERIAL PRIMARY KEY,
    city_id VARCHAR(64) NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    domain VARCHAR(64) NOT NULL,        -- Maps to entity domain
    primary_color VARCHAR(32),          -- Main color (CSS format)
    light_color VARCHAR(32),            -- Light variant for backgrounds
    dark_color VARCHAR(32),             -- Dark variant for text
    border_color VARCHAR(32),           -- Border color
    icon VARCHAR(64),                   -- Default icon for domain
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL,
    UNIQUE(city_id, domain)
);

CREATE INDEX IF NOT EXISTS color_schemes_city_id_idx ON color_schemes(city_id);

COMMENT ON TABLE color_schemes IS 'Visual styling for entity domains per city';

-- =============================================================================
-- Data Sources
-- =============================================================================
CREATE TABLE IF NOT EXISTS sources (
    id SERIAL PRIMARY KEY,
    city_id VARCHAR(64) NOT NULL,
    name VARCHAR(256) NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    driver_type VARCHAR(64) NOT NULL,
    url TEXT NOT NULL,
    config JSONB,
    is_enabled BOOLEAN DEFAULT TRUE NOT NULL,
    schedule_interval INTEGER DEFAULT 3600,
    last_fetched_at TIMESTAMP,
    last_success_at TIMESTAMP,
    last_error TEXT,
    consecutive_failures INTEGER DEFAULT 0 NOT NULL,
    trigger_requested_at TIMESTAMP,    -- Set by admin to request manual scrape
    entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL, -- Associated entity
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS sources_city_id_idx ON sources(city_id);
CREATE INDEX IF NOT EXISTS sources_source_type_idx ON sources(source_type);
CREATE INDEX IF NOT EXISTS sources_entity_id_idx ON sources(entity_id);

-- Migration: Add trigger_requested_at if it doesn't exist (for existing databases)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'sources' AND column_name = 'trigger_requested_at'
    ) THEN
        ALTER TABLE sources ADD COLUMN trigger_requested_at TIMESTAMP;
    END IF;
END $$;

-- Migration: Add entity_id if it doesn't exist (for existing databases)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'sources' AND column_name = 'entity_id'
    ) THEN
        ALTER TABLE sources ADD COLUMN entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS sources_entity_id_idx ON sources(entity_id);
    END IF;
END $$;

-- =============================================================================
-- Events (canonical event data - deduplicated across sources)
-- =============================================================================
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    title VARCHAR(512) NOT NULL,
    description TEXT,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    location VARCHAR(512),
    category VARCHAR(128),             -- Event category (meeting, recreation, community, etc.)
    is_cancelled BOOLEAN DEFAULT FALSE,
    is_virtual BOOLEAN DEFAULT FALSE,
    virtual_url TEXT,
    video_url TEXT,                    -- Recording URL (YouTube, Vimeo, etc.)
    ai_summary TEXT,                   -- AI-generated overview of the event
    ai_summary_updated_at TIMESTAMP,   -- When the AI summary was last generated
    ai_model_used VARCHAR(64),         -- AI model used to generate the summary
    summary_priority TIMESTAMP,        -- Higher (more recent) values processed first in AI queue (set on manual reanalysis)
    entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL, -- Associated entity
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS events_start_time_idx ON events(start_time);
CREATE INDEX IF NOT EXISTS events_summary_priority_idx ON events(summary_priority DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS events_category_idx ON events(category);
CREATE INDEX IF NOT EXISTS events_entity_id_idx ON events(entity_id);
-- Trigram index for fuzzy title matching
CREATE INDEX IF NOT EXISTS events_title_trgm_idx ON events USING GIN(title gin_trgm_ops);

-- Migration: Add entity_id to events if it doesn't exist (for existing databases)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'events' AND column_name = 'entity_id'
    ) THEN
        ALTER TABLE events ADD COLUMN entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS events_entity_id_idx ON events(entity_id);
    END IF;
END $$;

-- =============================================================================
-- Event Sources (tracks which sources reported each event)
-- =============================================================================
-- An event can come from multiple sources (e.g., same meeting on RSS + HTML calendar)
CREATE TABLE IF NOT EXISTS event_sources (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_id VARCHAR(256),          -- The ID this source uses for the event
    source_url TEXT,                   -- URL to event on this source
    raw_data JSONB,                    -- Original data from this source
    first_seen_at TIMESTAMP DEFAULT NOW() NOT NULL,
    last_seen_at TIMESTAMP DEFAULT NOW() NOT NULL,
    UNIQUE(event_id, source_id),
    UNIQUE(source_id, external_id)     -- Each source can only have one entry per external_id
);

CREATE INDEX IF NOT EXISTS event_sources_event_id_idx ON event_sources(event_id);
CREATE INDEX IF NOT EXISTS event_sources_source_id_idx ON event_sources(source_id);
CREATE INDEX IF NOT EXISTS event_sources_external_id_idx ON event_sources(source_id, external_id);

-- =============================================================================
-- Event-City Association (many-to-many)
-- =============================================================================
-- Links events to cities. Supports multi-city events (e.g., regional meetings)
-- where the same event may be referenced by sources from multiple cities.
CREATE TABLE IF NOT EXISTS event_cities (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    city_id VARCHAR(64) NOT NULL REFERENCES cities(city_id) ON DELETE CASCADE,
    is_primary BOOLEAN DEFAULT true,   -- The city that first discovered this event
    first_seen_at TIMESTAMP DEFAULT NOW() NOT NULL,
    last_seen_at TIMESTAMP DEFAULT NOW() NOT NULL,
    UNIQUE(event_id, city_id)
);

CREATE INDEX IF NOT EXISTS event_cities_event_id_idx ON event_cities(event_id);
CREATE INDEX IF NOT EXISTS event_cities_city_id_idx ON event_cities(city_id);
CREATE INDEX IF NOT EXISTS event_cities_primary_idx ON event_cities(event_id) WHERE is_primary = true;

COMMENT ON TABLE event_cities IS 'Links events to cities, supporting multi-city events';
COMMENT ON COLUMN event_cities.is_primary IS 'True if this city first discovered the event';

-- =============================================================================
-- Documents
-- =============================================================================
-- Content lifecycle statuses:
--   discovered        - Found by scraper, metadata only (visible as placeholder)
--   download_pending  - Queued for download
--   downloading       - Currently downloading
--   downloaded        - File saved locally
--   extraction_pending - Queued for text extraction
--   extracting        - Currently extracting text
--   extracted         - Text available
--   ai_pending        - Queued for AI summary
--   ai_processing     - AI generating summary
--   complete          - Fully processed
--   failed            - Processing failed
--   skipped           - Non-processable content
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_id VARCHAR(256),
    title VARCHAR(512) NOT NULL,
    document_type VARCHAR(64),
    content_text TEXT,
    content_markdown TEXT,
    source_url TEXT,
    file_url TEXT,
    file_hash VARCHAR(64),
    local_path TEXT,                   -- Local file path for downloaded files
    file_size_bytes BIGINT,            -- File size in bytes
    mime_type VARCHAR(128),            -- MIME type of the file
    ai_summary TEXT,                   -- AI-generated summary of the document
    ai_summary_updated_at TIMESTAMP,   -- When the AI summary was last generated
    ai_model_used VARCHAR(64),         -- AI model used to generate the summary
    published_date TIMESTAMP,          -- When the document was published/uploaded
    meeting_date TIMESTAMP,            -- Date of the meeting this document is for (for linking)
    
    -- Unified content lifecycle tracking
    content_status VARCHAR(32) DEFAULT 'discovered',  -- See statuses above
    error_message TEXT,                -- Last error if failed
    retry_count INTEGER DEFAULT 0,     -- Number of retry attempts
    retry_after TIMESTAMP,             -- When to retry (exponential backoff)
    
    -- Processing timestamps (for metrics and debugging)
    discovered_at TIMESTAMP,           -- When scraper first found this
    download_started_at TIMESTAMP,     -- When download began
    download_completed_at TIMESTAMP,   -- When download finished
    extraction_started_at TIMESTAMP,   -- When text extraction began
    extraction_completed_at TIMESTAMP, -- When text extraction finished
    ai_started_at TIMESTAMP,           -- When AI processing began
    ai_completed_at TIMESTAMP,         -- When AI processing finished
    
    -- Linking status tracking (for event association)
    linking_status VARCHAR(32),        -- NULL=new, 'pending', 'pending_retry', 'linked', 'blocked'
    linking_attempts INTEGER DEFAULT 0, -- Number of linking attempts
    linking_retry_after TIMESTAMP,     -- When to retry linking
    -- AI summary priority (for user-initiated priority)
    summary_priority TIMESTAMP,        -- Higher (more recent) values processed first in AI queue
    -- Legislation-specific fields (for ordinances, resolutions, etc.)
    legislation_number VARCHAR(32),    -- e.g., "01-25", "104-25"
    legislation_year INTEGER,          -- Year extracted from number (e.g., 2025)
    legislation_status legislation_status,  -- Current status
    proposed_date TIMESTAMP,           -- When first proposed
    first_reading_date TIMESTAMP,      -- First reading date
    second_reading_date TIMESTAMP,     -- Second reading date
    third_reading_date TIMESTAMP,      -- Third reading date (if applicable)
    final_action_date TIMESTAMP,       -- When approved/failed/vetoed
    entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL, -- Associated entity
    cascade_triggered_at TIMESTAMP,    -- When cascade was triggered for this document
    raw_data JSONB,
    search_vector TSVECTOR,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS documents_source_id_idx ON documents(source_id);
CREATE INDEX IF NOT EXISTS documents_document_type_idx ON documents(document_type);
CREATE INDEX IF NOT EXISTS documents_published_date_idx ON documents(published_date);
CREATE INDEX IF NOT EXISTS documents_meeting_date_idx ON documents(meeting_date);
CREATE INDEX IF NOT EXISTS documents_external_id_idx ON documents(source_id, external_id);
CREATE INDEX IF NOT EXISTS documents_search_idx ON documents USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS documents_linking_status_idx ON documents(linking_status);
CREATE INDEX IF NOT EXISTS documents_summary_priority_idx ON documents(summary_priority DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS documents_entity_id_idx ON documents(entity_id);
CREATE INDEX IF NOT EXISTS idx_documents_cascade_check 
ON documents(id, updated_at, cascade_triggered_at)
WHERE ai_summary IS NOT NULL AND ai_summary != '';
-- Content lifecycle queue indexes (for efficient queue retrieval)
CREATE INDEX IF NOT EXISTS documents_content_status_idx ON documents(content_status);
CREATE INDEX IF NOT EXISTS documents_content_status_date_idx ON documents(content_status, meeting_date DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS documents_retry_after_idx ON documents(retry_after) WHERE retry_after IS NOT NULL;
CREATE INDEX IF NOT EXISTS documents_download_queue_idx ON documents(content_status, meeting_date DESC NULLS LAST) 
    WHERE content_status IN ('discovered', 'download_pending');
CREATE INDEX IF NOT EXISTS documents_extraction_queue_idx ON documents(content_status, meeting_date DESC NULLS LAST) 
    WHERE content_status IN ('downloaded', 'extraction_pending');
CREATE INDEX IF NOT EXISTS documents_ai_queue_idx ON documents(content_status, meeting_date DESC NULLS LAST) 
    WHERE content_status IN ('extracted', 'ai_pending');
-- Legislation-specific indexes
CREATE INDEX IF NOT EXISTS documents_legislation_number_idx ON documents(legislation_number) WHERE document_type IN ('ordinance', 'resolution');
CREATE INDEX IF NOT EXISTS documents_legislation_year_idx ON documents(legislation_year) WHERE document_type IN ('ordinance', 'resolution');
CREATE INDEX IF NOT EXISTS documents_legislation_status_idx ON documents(legislation_status) WHERE document_type IN ('ordinance', 'resolution');
CREATE INDEX IF NOT EXISTS documents_proposed_date_idx ON documents(proposed_date) WHERE document_type IN ('ordinance', 'resolution');

-- Migration: Add entity_id to documents if it doesn't exist (for existing databases)
DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'documents' AND column_name = 'entity_id'
    ) THEN
        ALTER TABLE documents ADD COLUMN entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL;
        CREATE INDEX IF NOT EXISTS documents_entity_id_idx ON documents(entity_id);
    END IF;
END $$;

-- =============================================================================
-- Event-Document Association
-- =============================================================================
-- Links documents to their related events (e.g., agenda/minutes for a meeting)
CREATE TABLE IF NOT EXISTS event_documents (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    relationship VARCHAR(64) NOT NULL DEFAULT 'related',
    -- relationship types: 'agenda', 'minutes', 'packet', 'video', 'transcript', 'attachment', 'related'
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    UNIQUE(event_id, document_id)
);

CREATE INDEX IF NOT EXISTS event_documents_event_id_idx ON event_documents(event_id);
CREATE INDEX IF NOT EXISTS event_documents_document_id_idx ON event_documents(document_id);
CREATE INDEX IF NOT EXISTS event_documents_relationship_idx ON event_documents(relationship);

-- =============================================================================
-- Legislation Mentions
-- =============================================================================
-- Tracks when legislation (ordinances, resolutions, motions) is discussed/voted on in meetings
CREATE TABLE IF NOT EXISTS legislation_mentions (
    id SERIAL PRIMARY KEY,
    
    -- Document this mention was found in
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    
    -- Optional link to the event (meeting) if document is linked to one
    event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
    
    -- Legislation identification
    legislation_type VARCHAR(64) NOT NULL,    -- 'ordinance', 'resolution', 'motion', 'bylaw', 'proclamation'
    legislation_number VARCHAR(64) NOT NULL,  -- e.g., '2025-139', 'R-2025-12'
    legislation_title TEXT,                   -- Full title if available
    
    -- Action taken at this meeting
    action_taken legislation_action NOT NULL DEFAULT 'discussed',
    
    -- Vote information (if a vote occurred)
    vote_result VARCHAR(32),                  -- 'passed', 'failed', 'tabled', 'unanimous', null if no vote
    vote_details JSONB,                       -- {"yes": 5, "no": 2, "abstain": 0, "absent": 0, "votes": [...]}
    
    -- Context from the document
    excerpt TEXT,                             -- Relevant excerpt from document
    
    -- Metadata
    mentioned_date TIMESTAMP,                 -- Date of the meeting (derived from document or event)
    raw_data JSONB,                           -- Original AI extraction data
    
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS legislation_mentions_document_id_idx ON legislation_mentions(document_id);
CREATE INDEX IF NOT EXISTS legislation_mentions_event_id_idx ON legislation_mentions(event_id);
CREATE INDEX IF NOT EXISTS legislation_mentions_legislation_number_idx ON legislation_mentions(legislation_number);
CREATE INDEX IF NOT EXISTS legislation_mentions_legislation_type_idx ON legislation_mentions(legislation_type);
CREATE INDEX IF NOT EXISTS legislation_mentions_action_taken_idx ON legislation_mentions(action_taken);
CREATE INDEX IF NOT EXISTS legislation_mentions_mentioned_date_idx ON legislation_mentions(mentioned_date);
CREATE INDEX IF NOT EXISTS legislation_mentions_number_date_idx ON legislation_mentions(legislation_number, mentioned_date);
CREATE INDEX IF NOT EXISTS legislation_mentions_title_trgm_idx ON legislation_mentions USING GIN(legislation_title gin_trgm_ops);

CREATE TRIGGER update_legislation_mentions_updated_at BEFORE UPDATE ON legislation_mentions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Trigger to update search_vector
CREATE OR REPLACE FUNCTION documents_search_trigger() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := 
        setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', COALESCE(NEW.content_text, '')), 'B');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS documents_search_update ON documents;
CREATE TRIGGER documents_search_update
    BEFORE INSERT OR UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION documents_search_trigger();

-- =============================================================================
-- NextAuth Tables
-- =============================================================================
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT NOT NULL UNIQUE,
    email_verified TIMESTAMP,
    image TEXT,
    role VARCHAR(32) DEFAULT 'user' NOT NULL,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_account_id TEXT NOT NULL,
    refresh_token TEXT,
    access_token TEXT,
    expires_at INTEGER,
    token_type TEXT,
    scope TEXT,
    id_token TEXT,
    session_state TEXT,
    PRIMARY KEY (provider, provider_account_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS verification_tokens (
    identifier TEXT NOT NULL,
    token TEXT NOT NULL,
    expires TIMESTAMP NOT NULL,
    PRIMARY KEY (identifier, token)
);

-- =============================================================================
-- Scraper Logs
-- =============================================================================
CREATE TABLE IF NOT EXISTS scraper_logs (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL,
    message TEXT,
    events_found INTEGER DEFAULT 0,
    documents_found INTEGER DEFAULT 0,
    duration INTEGER,
    error_details JSONB,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS scraper_logs_source_id_idx ON scraper_logs(source_id);
CREATE INDEX IF NOT EXISTS scraper_logs_status_idx ON scraper_logs(status);
CREATE INDEX IF NOT EXISTS scraper_logs_created_at_idx ON scraper_logs(created_at);

-- =============================================================================
-- Update Timestamp Triggers (function defined at top of file)
-- =============================================================================
-- Apply to all tables with updated_at
CREATE TRIGGER update_cities_updated_at BEFORE UPDATE ON cities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_sources_updated_at BEFORE UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_events_updated_at BEFORE UPDATE ON events
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Summaries (Cascading AI-generated summaries: event → daily → weekly → etc.)
-- =============================================================================
CREATE TABLE IF NOT EXISTS summaries (
    id SERIAL PRIMARY KEY,
    city_id VARCHAR(64) NOT NULL,
    
    -- What this summary covers
    summary_type VARCHAR(32) NOT NULL,  -- 'event', 'daily', 'weekly', 'monthly', 'quarterly', 'annual'
    period_start TIMESTAMP NOT NULL,    -- Start of the period covered
    period_end TIMESTAMP NOT NULL,      -- End of the period covered
    
    -- For event summaries, link to the event
    event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
    
    -- The generated content
    title VARCHAR(512),
    summary_text TEXT,                  -- AI-generated markdown summary
    key_points JSONB,                   -- [{point: "...", category: "decision|discussion|announcement"}]
    
    -- Tracking completeness (primarily for event summaries)
    documents_included INTEGER[],       -- Document IDs included in this summary
    expected_document_types TEXT[],     -- ['agenda', 'minutes', 'video', 'packet']
    completeness_score FLOAT,           -- 0.0 to 1.0 (how complete is the data)
    
    -- Child summary tracking (for daily/weekly/etc.)
    child_summary_count INTEGER DEFAULT 0,  -- Number of child summaries included
    
    -- Versioning
    version INTEGER DEFAULT 1,
    previous_version_id INTEGER REFERENCES summaries(id),
    
    -- Generation status
    status VARCHAR(32) DEFAULT 'pending' NOT NULL, -- 'pending', 'generating', 'completed', 'failed', 'stale'
    is_stale BOOLEAN DEFAULT false,     -- Marked for regeneration
    
    -- Generation metadata
    generation_triggered_by VARCHAR(64), -- 'document_added', 'child_updated', 'scheduled', 'manual'
    triggered_by_id INTEGER,             -- ID of document/summary that triggered regeneration
    generation_started_at TIMESTAMP,
    generation_completed_at TIMESTAMP,
    token_count INTEGER,                 -- Track AI token usage
    model_used VARCHAR(64),              -- AI model used to generate this summary
    error_message TEXT,
    
    -- Legacy fields for backwards compatibility
    pdf_path TEXT,
    pdf_url TEXT,
    
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS summaries_city_type_idx ON summaries(city_id, summary_type);
CREATE INDEX IF NOT EXISTS summaries_period_idx ON summaries(period_start, period_end);
CREATE INDEX IF NOT EXISTS summaries_event_idx ON summaries(event_id) WHERE event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS summaries_status_idx ON summaries(status);
CREATE INDEX IF NOT EXISTS summaries_stale_idx ON summaries(is_stale) WHERE is_stale = true;

-- Unique constraint for event summaries (one per event per city)
CREATE UNIQUE INDEX IF NOT EXISTS summaries_event_unique_idx 
    ON summaries(city_id, event_id) WHERE event_id IS NOT NULL;

-- Unique constraint for period summaries (one per period type per city)
CREATE UNIQUE INDEX IF NOT EXISTS summaries_period_unique_idx 
    ON summaries(city_id, summary_type, period_start) WHERE event_id IS NULL;

CREATE TRIGGER update_summaries_updated_at BEFORE UPDATE ON summaries
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Summary Triggers (audit trail for cascade regeneration)
-- =============================================================================
CREATE TABLE IF NOT EXISTS summary_triggers (
    id SERIAL PRIMARY KEY,
    summary_id INTEGER REFERENCES summaries(id) ON DELETE CASCADE,
    triggered_by_summary_id INTEGER REFERENCES summaries(id) ON DELETE SET NULL,
    triggered_by_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    trigger_reason VARCHAR(128),        -- 'document_added', 'document_updated', 'child_summary_updated'
    created_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS summary_triggers_summary_idx ON summary_triggers(summary_id);
CREATE INDEX IF NOT EXISTS summary_triggers_created_idx ON summary_triggers(created_at);

-- =============================================================================
-- Helper Functions for Legislation
-- =============================================================================

-- Get legislation history across all documents
CREATE OR REPLACE FUNCTION get_legislation_history(
    p_legislation_number VARCHAR(64),
    p_city_id VARCHAR(64) DEFAULT NULL
) RETURNS TABLE (
    mention_id INTEGER,
    document_id INTEGER,
    document_title VARCHAR(512),
    event_id INTEGER,
    event_title VARCHAR(512),
    legislation_type VARCHAR(64),
    legislation_title TEXT,
    action_taken legislation_action,
    vote_result VARCHAR(32),
    vote_details JSONB,
    excerpt TEXT,
    mentioned_date TIMESTAMP,
    source_name VARCHAR(256)
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        lm.id as mention_id,
        lm.document_id,
        d.title as document_title,
        lm.event_id,
        e.title as event_title,
        lm.legislation_type,
        lm.legislation_title,
        lm.action_taken,
        lm.vote_result,
        lm.vote_details,
        lm.excerpt,
        lm.mentioned_date,
        s.name as source_name
    FROM legislation_mentions lm
    JOIN documents d ON lm.document_id = d.id
    JOIN sources s ON d.source_id = s.id
    LEFT JOIN events e ON lm.event_id = e.id
    WHERE 
        lm.legislation_number ILIKE p_legislation_number
        AND (p_city_id IS NULL OR s.city_id = p_city_id)
    ORDER BY lm.mentioned_date ASC NULLS LAST;
END;
$$ LANGUAGE plpgsql;

-- Search legislation by title/number
CREATE OR REPLACE FUNCTION search_legislation(
    p_query TEXT,
    p_city_id VARCHAR(64) DEFAULT NULL,
    p_limit INTEGER DEFAULT 20
) RETURNS TABLE (
    legislation_number VARCHAR(64),
    legislation_type VARCHAR(64),
    legislation_title TEXT,
    mention_count BIGINT,
    latest_action legislation_action,
    latest_vote_result VARCHAR(32),
    latest_date TIMESTAMP,
    first_date TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    WITH ranked_mentions AS (
        SELECT 
            lm.legislation_number,
            lm.legislation_type,
            lm.legislation_title,
            lm.action_taken,
            lm.vote_result,
            lm.mentioned_date,
            ROW_NUMBER() OVER (
                PARTITION BY lm.legislation_number 
                ORDER BY lm.mentioned_date DESC NULLS LAST
            ) as rn
        FROM legislation_mentions lm
        JOIN documents d ON lm.document_id = d.id
        JOIN sources s ON d.source_id = s.id
        WHERE 
            (p_city_id IS NULL OR s.city_id = p_city_id)
            AND (
                lm.legislation_number ILIKE '%' || p_query || '%'
                OR lm.legislation_title ILIKE '%' || p_query || '%'
            )
    )
    SELECT 
        rm.legislation_number,
        rm.legislation_type,
        rm.legislation_title,
        COUNT(*) as mention_count,
        MAX(CASE WHEN rm.rn = 1 THEN rm.action_taken END) as latest_action,
        MAX(CASE WHEN rm.rn = 1 THEN rm.vote_result END) as latest_vote_result,
        MAX(rm.mentioned_date) as latest_date,
        MIN(rm.mentioned_date) as first_date
    FROM ranked_mentions rm
    GROUP BY rm.legislation_number, rm.legislation_type, rm.legislation_title
    ORDER BY latest_date DESC NULLS LAST
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Helper Functions for Event Deduplication
-- =============================================================================

-- Find events with similar titles within a time window
CREATE OR REPLACE FUNCTION find_similar_events(
    p_title TEXT,
    p_start_time TIMESTAMP,
    p_time_window INTERVAL DEFAULT '4 hours'
) RETURNS TABLE (
    event_id INTEGER,
    title VARCHAR(512),
    start_time TIMESTAMP,
    location VARCHAR(512),
    category VARCHAR(128),
    similarity REAL,
    source_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        e.id as event_id,
        e.title,
        e.start_time,
        e.location,
        e.category,
        similarity(e.title, p_title) as similarity,
        COUNT(DISTINCT es.source_id) as source_count
    FROM events e
    LEFT JOIN event_sources es ON e.id = es.event_id
    WHERE 
        -- Time window match
        e.start_time BETWEEN (p_start_time - p_time_window) AND (p_start_time + p_time_window)
        -- Title similarity threshold (0.3 is fairly loose)
        AND similarity(e.title, p_title) > 0.3
    GROUP BY e.id, e.title, e.start_time, e.location, e.category
    ORDER BY similarity(e.title, p_title) DESC
    LIMIT 10;
END;
$$ LANGUAGE plpgsql;

-- View for events with all their sources
CREATE OR REPLACE VIEW events_with_sources AS
SELECT 
    e.id,
    e.title,
    e.description,
    e.start_time,
    e.end_time,
    e.location,
    e.category,
    e.is_cancelled,
    e.is_virtual,
    e.virtual_url,
    e.video_url,
    e.created_at,
    e.updated_at,
    COALESCE(array_agg(DISTINCT s.name) FILTER (WHERE s.name IS NOT NULL), ARRAY[]::VARCHAR[]) as source_names,
    COALESCE(array_agg(DISTINCT es.source_url) FILTER (WHERE es.source_url IS NOT NULL), ARRAY[]::TEXT[]) as source_urls,
    COUNT(DISTINCT es.source_id) as source_count
FROM events e
LEFT JOIN event_sources es ON e.id = es.event_id
LEFT JOIN sources s ON es.source_id = s.id
GROUP BY e.id;

-- =============================================================================
-- Activity Log (for admin dashboard)
-- =============================================================================
CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    level VARCHAR(20) NOT NULL,           -- info, warning, error, success
    category VARCHAR(50) NOT NULL,        -- download, extraction, ai, scrape, system, event, linking
    action VARCHAR(100) NOT NULL,         -- started, completed, failed, queued, discovered, etc.
    entity_type VARCHAR(50),              -- document, event, source, summary
    entity_id INTEGER,
    entity_title TEXT,
    message TEXT,
    details JSONB,                        -- additional context (error messages, file sizes, etc.)
    source_name VARCHAR(255),
    city_id VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS activity_log_timestamp_idx ON activity_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS activity_log_level_idx ON activity_log(level);
CREATE INDEX IF NOT EXISTS activity_log_category_idx ON activity_log(category);
CREATE INDEX IF NOT EXISTS activity_log_entity_idx ON activity_log(entity_type, entity_id);

-- Auto-cleanup old activity logs (keep 7 days by default)
CREATE OR REPLACE FUNCTION cleanup_old_activity_logs()
RETURNS void AS $$
BEGIN
    DELETE FROM activity_log WHERE timestamp < NOW() - INTERVAL '7 days';
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Grants: Permissions for application role
-- =============================================================================
GRANT CONNECT ON DATABASE civic_commons TO civic_commons;
GRANT USAGE ON SCHEMA public TO civic_commons;

-- Grant permissions on all tables
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO civic_commons;

-- Grant permissions on all sequences (for auto-increment)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO civic_commons;

-- Grant permissions on all functions
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO civic_commons;

-- =============================================================================
-- Done
-- =============================================================================
DO $$
BEGIN
    RAISE NOTICE 'Civic Commons database initialized successfully!';
    RAISE NOTICE 'Cities: %', (SELECT COUNT(*) FROM cities);
    RAISE NOTICE 'Sources: %', (SELECT COUNT(*) FROM sources);
    RAISE NOTICE 'Events: %', (SELECT COUNT(*) FROM events);
    RAISE NOTICE 'Documents: %', (SELECT COUNT(*) FROM documents);
END $$;

