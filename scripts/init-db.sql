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
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS sources_city_id_idx ON sources(city_id);
CREATE INDEX IF NOT EXISTS sources_source_type_idx ON sources(source_type);

-- =============================================================================
-- Events
-- =============================================================================
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_id VARCHAR(256),
    title VARCHAR(512) NOT NULL,
    description TEXT,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    location VARCHAR(512),
    source_url TEXT,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS events_source_id_idx ON events(source_id);
CREATE INDEX IF NOT EXISTS events_start_time_idx ON events(start_time);
CREATE INDEX IF NOT EXISTS events_external_id_idx ON events(source_id, external_id);

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
    published_date TIMESTAMP,
    raw_data JSONB,
    search_vector TSVECTOR,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS documents_source_id_idx ON documents(source_id);
CREATE INDEX IF NOT EXISTS documents_document_type_idx ON documents(document_type);
CREATE INDEX IF NOT EXISTS documents_published_date_idx ON documents(published_date);
CREATE INDEX IF NOT EXISTS documents_external_id_idx ON documents(source_id, external_id);
CREATE INDEX IF NOT EXISTS documents_search_idx ON documents USING GIN(search_vector);

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

-- Insert sources for Twinsburg
INSERT INTO sources (city_id, name, source_type, driver_type, url, config, schedule_interval)
VALUES 
    ('twinsburg', 'City Council', 'city_council', 'civic_plus', 'https://www.mytwinsburg.com/AgendaCenter', '{"selectors": {"event_list": ".meeting-list"}}', 86400),
    ('twinsburg', 'School Board', 'school_board', 'civic_plus', 'https://www.twinsburg.k12.oh.us/BoardOfEducation', '{}', 14400),
    ('twinsburg', 'Public Library', 'library', 'libcal', 'https://cuyahogalibrary.libcal.com', '{"library_id": "twinsburg"}', 86400),
    ('twinsburg', 'Historical Society', 'historical_society', 'rss', 'https://twinsburghistoricalsociety.org/feed/', '{}', 86400),
    ('twinsburg', 'Parks & Recreation', 'parks_and_rec', 'civic_plus', 'https://www.mytwinsburg.com/parks', '{}', 86400),
    ('twinsburg', 'Cleveland Metroparks', 'metroparks', 'json_api', 'https://www.clevelandmetroparks.com/api/events', '{"region": "twinsburg"}', 86400);

-- =============================================================================
-- Done
-- =============================================================================
DO $$
BEGIN
    RAISE NOTICE 'Civic Commons database initialized successfully!';
    RAISE NOTICE 'Cities: %', (SELECT COUNT(*) FROM cities);
    RAISE NOTICE 'Sources: %', (SELECT COUNT(*) FROM sources);
END $$;
