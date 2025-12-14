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
    video_url TEXT,
    -- video_url: YouTube, Vimeo, or other video platform URL for meeting recording
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
-- Seed Data: Sample Events
-- =============================================================================
INSERT INTO events (source_id, external_id, title, description, start_time, end_time, location, source_url, video_url)
VALUES 
    -- Past City Council meetings with real video
    (1, 'cc-2025-10-28', 'City Council Meeting', 'Regular session of Twinsburg City Council.', '2025-10-28 19:00:00', '2025-10-28 21:00:00', 'Twinsburg City Hall, 10075 Ravenna Rd', 'https://www.mytwinsburg.com/AgendaCenter', 'https://www.youtube.com/live/mx1bKdi5OyI'),
    -- Past City Council meeting (has minutes + placeholder video)
    (1, 'cc-2025-12-03', 'City Council Meeting', 'Regular session of Twinsburg City Council.', '2025-12-03 19:00:00', '2025-12-03 21:00:00', 'Twinsburg City Hall, 10075 Ravenna Rd', 'https://www.mytwinsburg.com/AgendaCenter', NULL),
    -- Upcoming City Council meeting (has agenda, no video yet)
    (1, 'cc-2025-12-17', 'City Council Meeting', 'Regular session of Twinsburg City Council. Public comment period at 7:15 PM.', '2025-12-17 19:00:00', '2025-12-17 21:00:00', 'Twinsburg City Hall, 10075 Ravenna Rd', 'https://www.mytwinsburg.com/AgendaCenter', NULL),
    -- Planning Commission
    (1, 'pc-2025-12-19', 'Planning Commission Meeting', 'Review of zoning variance requests and site plan approvals.', '2025-12-19 18:30:00', '2025-12-19 20:30:00', 'Twinsburg City Hall, 10075 Ravenna Rd', 'https://www.mytwinsburg.com/AgendaCenter', NULL),
    -- School Board (placeholder - replace with real video URLs when available)
    (2, 'sb-2025-11-18', 'School Board Meeting', 'Monthly school board meeting. Budget review and curriculum updates.', '2025-11-18 18:00:00', '2025-11-18 20:00:00', 'Twinsburg High School, 10084 Ravenna Rd', 'https://www.twinsburg.k12.oh.us', NULL),
    (2, 'sb-2025-12-16', 'School Board Meeting', 'Monthly school board meeting.', '2025-12-16 18:00:00', '2025-12-16 20:00:00', 'Twinsburg High School, 10084 Ravenna Rd', 'https://www.twinsburg.k12.oh.us', NULL),
    -- Library events (no video)
    (3, 'lib-storytime-1221', 'Holiday Story Time', 'Join us for holiday stories and crafts! Ages 3-7.', '2025-12-21 10:00:00', '2025-12-21 11:00:00', 'Twinsburg Public Library', 'https://cuyahogalibrary.libcal.com', NULL),
    (3, 'lib-bookclub-1218', 'Book Club: Winter Reads', 'Discussion of this months selection. New members welcome!', '2025-12-18 19:00:00', '2025-12-18 20:30:00', 'Twinsburg Public Library', 'https://cuyahogalibrary.libcal.com', NULL),
    -- Parks event (no video)
    (5, 'parks-winter-1222', 'Winter Wonderland in the Park', 'Family fun event with hot cocoa, caroling, and Santa!', '2025-12-22 14:00:00', '2025-12-22 17:00:00', 'Twinsburg Town Square', 'https://www.mytwinsburg.com/parks', NULL);

-- =============================================================================
-- Seed Data: Sample Documents
-- =============================================================================
INSERT INTO documents (source_id, external_id, title, document_type, content_text, source_url, published_date)
VALUES 
    -- City Council Dec 3 meeting documents
    (1, 'cc-agenda-2025-12-03', 'City Council Agenda - December 3, 2025', 'agenda', 
     'AGENDA - Twinsburg City Council Regular Meeting, December 3, 2025 at 7:00 PM. 1. Call to Order. 2. Roll Call. 3. Approval of Minutes from November 19. 4. Public Comment Period. 5. Ordinance 2025-45: Street improvement project. 6. Resolution 2025-87: Emergency services contract. 7. Finance Committee Report. 8. City Manager Report. 9. Council Comments. 10. Adjournment.',
     'https://www.mytwinsburg.com/AgendaCenter', '2025-12-01'),
    (1, 'cc-minutes-2025-12-03', 'City Council Minutes - December 3, 2025', 'minutes', 
     'MINUTES - Twinsburg City Council Regular Meeting, December 3, 2025. Council President Smith called the meeting to order at 7:00 PM. Roll call: All members present. Motion to approve minutes from November 19 meeting passed unanimously. Public comment period: Three residents spoke regarding proposed zoning changes on Darrow Road. Finance Director presented Q3 budget update showing revenues exceeding projections by 3.2%. Ordinance 2025-45 approved 6-1. Resolution 2025-87 approved unanimously. Meeting adjourned at 9:15 PM.',
     'https://www.mytwinsburg.com/AgendaCenter', '2025-12-04'),
    -- City Council Dec 17 meeting documents
    (1, 'cc-agenda-2025-12-17', 'City Council Agenda - December 17, 2025', 'agenda', 
     'AGENDA - Twinsburg City Council Regular Meeting, December 17, 2025 at 7:00 PM. 1. Call to Order. 2. Roll Call. 3. Approval of Minutes from December 3. 4. Public Comment Period (7:15 PM). 5. Ordinance 2025-47: Rezoning request for 1234 Ravenna Road. 6. Resolution 2025-89: Snow removal contract renewal. 7. Finance Committee Report - Year End Review. 8. City Manager Report. 9. Council Comments. 10. Adjournment.',
     'https://www.mytwinsburg.com/AgendaCenter', '2025-12-13'),
    -- School Board documents
    (2, 'sb-agenda-2025-11-18', 'School Board Agenda - November 18, 2025', 'agenda',
     'AGENDA - Twinsburg City School District Board of Education, November 18, 2025. 1. Call to Order. 2. Pledge of Allegiance. 3. Approval of Minutes. 4. Superintendent Report - Literacy Initiative Update. 5. Treasurer Report. 6. New Business: Science Lab Equipment Purchase. 7. 2026-2027 Academic Calendar Discussion. 8. Public Comment. 9. Adjournment.',
     'https://www.twinsburg.k12.oh.us', '2025-11-15'),
    (2, 'sb-minutes-2025-11-18', 'School Board Minutes - November 18, 2025', 'minutes', 
     'MINUTES - Twinsburg City School District Board of Education, November 18, 2025. Meeting called to order at 6:00 PM. All board members present. Superintendent Williams presented update on literacy initiative showing 12% improvement in K-3 reading scores. Board approved purchase of new science lab equipment for high school ($45,000). Discussion of proposed 2026-2027 academic calendar - first day August 18, last day May 28. Public comment: Two parents spoke in support of extended library hours. Meeting adjourned at 7:45 PM.',
     'https://www.twinsburg.k12.oh.us', '2025-11-19');

-- =============================================================================
-- Seed Data: Event-Document Associations
-- =============================================================================
-- Link documents to their events
INSERT INTO event_documents (event_id, document_id, relationship)
SELECT e.id, d.id, 'agenda'
FROM events e, documents d
WHERE e.external_id = 'cc-2025-12-03' AND d.external_id = 'cc-agenda-2025-12-03';

INSERT INTO event_documents (event_id, document_id, relationship)
SELECT e.id, d.id, 'minutes'
FROM events e, documents d
WHERE e.external_id = 'cc-2025-12-03' AND d.external_id = 'cc-minutes-2025-12-03';

INSERT INTO event_documents (event_id, document_id, relationship)
SELECT e.id, d.id, 'agenda'
FROM events e, documents d
WHERE e.external_id = 'cc-2025-12-17' AND d.external_id = 'cc-agenda-2025-12-17';

INSERT INTO event_documents (event_id, document_id, relationship)
SELECT e.id, d.id, 'agenda'
FROM events e, documents d
WHERE e.external_id = 'sb-2025-11-18' AND d.external_id = 'sb-agenda-2025-11-18';

INSERT INTO event_documents (event_id, document_id, relationship)
SELECT e.id, d.id, 'minutes'
FROM events e, documents d
WHERE e.external_id = 'sb-2025-11-18' AND d.external_id = 'sb-minutes-2025-11-18';

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
    RAISE NOTICE 'Event-Document links: %', (SELECT COUNT(*) FROM event_documents);
END $$;
