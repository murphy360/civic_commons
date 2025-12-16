-- Civic Commons Database Schema
-- Automatically runs on first container start via docker-entrypoint-initdb.d

-- =============================================================================
-- Extensions
-- =============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================================================
-- City Configuration
-- =============================================================================
CREATE TABLE IF NOT EXISTS cities (
    id SERIAL PRIMARY KEY,
    city_id VARCHAR(64) NOT NULL UNIQUE,
    display_name VARCHAR(256) NOT NULL,
    assistant_name VARCHAR(128),
    assistant_persona TEXT,
    timezone VARCHAR(64) DEFAULT 'America/New_York',
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS cities_city_id_idx ON cities(city_id);

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
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS sources_city_id_idx ON sources(city_id);
CREATE INDEX IF NOT EXISTS sources_source_type_idx ON sources(source_type);

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
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS events_start_time_idx ON events(start_time);
CREATE INDEX IF NOT EXISTS events_category_idx ON events(category);
-- Trigram index for fuzzy title matching
CREATE INDEX IF NOT EXISTS events_title_trgm_idx ON events USING GIN(title gin_trgm_ops);

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
-- Documents
-- =============================================================================
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
    published_date TIMESTAMP,          -- When the document was published/uploaded
    meeting_date TIMESTAMP,            -- Date of the meeting this document is for (for linking)
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
-- Update Timestamp Trigger
-- =============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

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
-- Seed Data: Twinsburg Configuration
-- =============================================================================
INSERT INTO cities (city_id, display_name, assistant_name, assistant_persona, timezone)
VALUES (
    'twinsburg',
    'Twinsburg, Ohio',
    'TwinBot',
    'You are TwinBot, a friendly and knowledgeable assistant for Twinsburg, Ohio. You help residents find information about local government, events, and community resources. You speak in a warm, helpful tone and always cite your sources.',
    'America/New_York'
);

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

