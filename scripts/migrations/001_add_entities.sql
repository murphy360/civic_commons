-- Migration: Add Entities Support
-- Adds entity normalization for consistent labeling and color-coding of events
-- Run with: psql -h localhost -U commons -d civic_commons -f scripts/migrations/001_add_entities.sql

-- =============================================================================
-- Entities Table
-- =============================================================================
-- Entities represent civic bodies, organizations, and institutions.
-- Each entity belongs to a domain (for color-coding) and may have a parent.

CREATE TABLE IF NOT EXISTS entities (
    id SERIAL PRIMARY KEY,
    city_id VARCHAR(64) NOT NULL,
    entity_key VARCHAR(128) NOT NULL,          -- Unique key from config (e.g., "city_council")
    display_name VARCHAR(256) NOT NULL,        -- Full name (e.g., "City Council")
    short_name VARCHAR(64),                    -- Abbreviated name (e.g., "Council")
    domain VARCHAR(64) NOT NULL,               -- Color domain: civic, education, community, recreation, business
    entity_type VARCHAR(64),                   -- Type: municipality, legislative_body, commission, board, school, etc.
    parent_entity_key VARCHAR(128),            -- Parent entity key (for hierarchy)
    parent_entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL,
    aliases TEXT[],                            -- Alternative names for matching
    icon VARCHAR(16),                          -- Emoji icon for display
    metadata JSONB,                            -- Additional config data
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL,
    UNIQUE(city_id, entity_key)
);

CREATE INDEX IF NOT EXISTS entities_city_id_idx ON entities(city_id);
CREATE INDEX IF NOT EXISTS entities_domain_idx ON entities(domain);
CREATE INDEX IF NOT EXISTS entities_entity_key_idx ON entities(entity_key);
CREATE INDEX IF NOT EXISTS entities_parent_entity_id_idx ON entities(parent_entity_id);

-- Trigger to update updated_at
DROP TRIGGER IF EXISTS update_entities_updated_at ON entities;
CREATE TRIGGER update_entities_updated_at BEFORE UPDATE ON entities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Color Schemes Table
-- =============================================================================
-- Stores domain color definitions from config for UI rendering

CREATE TABLE IF NOT EXISTS color_schemes (
    id SERIAL PRIMARY KEY,
    city_id VARCHAR(64) NOT NULL,
    domain VARCHAR(64) NOT NULL,               -- civic, education, community, recreation, business
    primary_color VARCHAR(32) NOT NULL,        -- Tailwind color class (e.g., "blue-600")
    light_color VARCHAR(32) NOT NULL,          -- Light variant (e.g., "blue-100")
    dark_color VARCHAR(32) NOT NULL,           -- Dark variant (e.g., "blue-800")
    border_color VARCHAR(32) NOT NULL,         -- Border color (e.g., "blue-300")
    icon VARCHAR(16),                          -- Default emoji icon for domain
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL,
    UNIQUE(city_id, domain)
);

CREATE INDEX IF NOT EXISTS color_schemes_city_id_idx ON color_schemes(city_id);

-- =============================================================================
-- Add entity_id to sources table
-- =============================================================================
-- Links sources to their owning entity

DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'sources' AND column_name = 'entity_id'
    ) THEN
        ALTER TABLE sources ADD COLUMN entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS sources_entity_id_idx ON sources(entity_id);

-- =============================================================================
-- Add entity_id to events table
-- =============================================================================
-- Links events to their primary entity (derived from source on import)

DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'events' AND column_name = 'entity_id'
    ) THEN
        ALTER TABLE events ADD COLUMN entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS events_entity_id_idx ON events(entity_id);

-- =============================================================================
-- Add entity_id to documents table
-- =============================================================================
-- Links documents to their primary entity (derived from source on import)

DO $$ 
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'documents' AND column_name = 'entity_id'
    ) THEN
        ALTER TABLE documents ADD COLUMN entity_id INTEGER REFERENCES entities(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS documents_entity_id_idx ON documents(entity_id);

-- =============================================================================
-- Entity Tags Table (Optional - for additional categorization)
-- =============================================================================
-- Allows tagging events with additional descriptors beyond entity

CREATE TABLE IF NOT EXISTS tag_definitions (
    id SERIAL PRIMARY KEY,
    city_id VARCHAR(64) NOT NULL,
    tag_key VARCHAR(64) NOT NULL,              -- Unique tag key (e.g., "public_hearing")
    display_name VARCHAR(128) NOT NULL,        -- Display name (e.g., "Public Hearing")
    category VARCHAR(64),                      -- Tag category (e.g., "meeting_type", "topic")
    color VARCHAR(32),                         -- Optional color override
    icon VARCHAR(16),                          -- Optional icon
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    UNIQUE(city_id, tag_key)
);

CREATE INDEX IF NOT EXISTS tag_definitions_city_id_idx ON tag_definitions(city_id);

CREATE TABLE IF NOT EXISTS event_tags (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tag_definitions(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    UNIQUE(event_id, tag_id)
);

CREATE INDEX IF NOT EXISTS event_tags_event_id_idx ON event_tags(event_id);
CREATE INDEX IF NOT EXISTS event_tags_tag_id_idx ON event_tags(tag_id);

-- =============================================================================
-- Views for easier querying
-- =============================================================================

-- View: Events with entity and color information
CREATE OR REPLACE VIEW events_with_entity AS
SELECT 
    e.*,
    ent.entity_key,
    ent.display_name AS entity_display_name,
    ent.short_name AS entity_short_name,
    ent.domain AS entity_domain,
    ent.entity_type,
    ent.icon AS entity_icon,
    cs.primary_color,
    cs.light_color,
    cs.dark_color,
    cs.border_color
FROM events e
LEFT JOIN entities ent ON e.entity_id = ent.id
LEFT JOIN color_schemes cs ON ent.domain = cs.domain AND ent.city_id = cs.city_id;

-- View: Documents with entity and color information
CREATE OR REPLACE VIEW documents_with_entity AS
SELECT 
    d.*,
    ent.entity_key,
    ent.display_name AS entity_display_name,
    ent.short_name AS entity_short_name,
    ent.domain AS entity_domain,
    ent.entity_type,
    ent.icon AS entity_icon,
    cs.primary_color,
    cs.light_color,
    cs.dark_color,
    cs.border_color
FROM documents d
LEFT JOIN entities ent ON d.entity_id = ent.id
LEFT JOIN color_schemes cs ON ent.domain = cs.domain AND ent.city_id = cs.city_id;

-- View: Sources with entity information
CREATE OR REPLACE VIEW sources_with_entity AS
SELECT 
    s.*,
    ent.entity_key,
    ent.display_name AS entity_display_name,
    ent.short_name AS entity_short_name,
    ent.domain AS entity_domain,
    ent.entity_type,
    ent.icon AS entity_icon
FROM sources s
LEFT JOIN entities ent ON s.entity_id = ent.id;

-- =============================================================================
-- Grant permissions (match existing grants in init-db.sql)
-- =============================================================================
-- Assuming 'commons' user from docker-compose

GRANT ALL PRIVILEGES ON entities TO commons;
GRANT ALL PRIVILEGES ON color_schemes TO commons;
GRANT ALL PRIVILEGES ON tag_definitions TO commons;
GRANT ALL PRIVILEGES ON event_tags TO commons;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO commons;
