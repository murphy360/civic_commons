-- Migration: Add legislation_mentions table
-- Tracks when legislation (ordinances, resolutions, motions) is discussed/voted on in meetings
-- Run with: psql -f scripts/migrations/001_add_legislation_mentions.sql

-- =============================================================================
-- Legislation Action Type
-- =============================================================================
DO $$ BEGIN
    CREATE TYPE legislation_action AS ENUM (
        'introduced',        -- First time legislation appears
        'first_reading',     -- First reading (required before vote)
        'second_reading',    -- Second reading (often final before vote)
        'third_reading',     -- Third reading (if required)
        'public_hearing',    -- Public hearing scheduled/held
        'amended',           -- Legislation was amended
        'tabled',            -- Postponed for future consideration
        'referred',          -- Referred to committee
        'approved',          -- Passed/adopted
        'failed',            -- Did not pass
        'vetoed',            -- Vetoed by executive
        'withdrawn',         -- Withdrawn by sponsor
        'discussed'          -- General discussion (no specific action)
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- =============================================================================
-- Legislation Mentions Table
-- =============================================================================
-- Links documents (typically meeting minutes/agendas) to specific legislation
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
    vote_details JSONB,                       -- {"yes": 5, "no": 2, "abstain": 0, "absent": 0, "votes": [{"name": "...", "vote": "yes"}]}
    
    -- Context from the document
    excerpt TEXT,                             -- Relevant excerpt from document
    
    -- Metadata
    mentioned_date TIMESTAMP,                 -- Date of the meeting (derived from document or event)
    raw_data JSONB,                           -- Original AI extraction data
    
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS legislation_mentions_document_id_idx 
    ON legislation_mentions(document_id);

CREATE INDEX IF NOT EXISTS legislation_mentions_event_id_idx 
    ON legislation_mentions(event_id);

CREATE INDEX IF NOT EXISTS legislation_mentions_legislation_number_idx 
    ON legislation_mentions(legislation_number);

CREATE INDEX IF NOT EXISTS legislation_mentions_legislation_type_idx 
    ON legislation_mentions(legislation_type);

CREATE INDEX IF NOT EXISTS legislation_mentions_action_taken_idx 
    ON legislation_mentions(action_taken);

CREATE INDEX IF NOT EXISTS legislation_mentions_mentioned_date_idx 
    ON legislation_mentions(mentioned_date);

-- Composite index for finding legislation history
CREATE INDEX IF NOT EXISTS legislation_mentions_number_date_idx 
    ON legislation_mentions(legislation_number, mentioned_date);

-- Full text search on legislation title
CREATE INDEX IF NOT EXISTS legislation_mentions_title_trgm_idx 
    ON legislation_mentions USING GIN(legislation_title gin_trgm_ops);

-- =============================================================================
-- Updated at trigger
-- =============================================================================
CREATE TRIGGER update_legislation_mentions_updated_at 
    BEFORE UPDATE ON legislation_mentions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Helper function: Get legislation history
-- =============================================================================
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

-- =============================================================================
-- Helper function: Search legislation by title/number
-- =============================================================================
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
-- Done
-- =============================================================================
DO $$
BEGIN
    RAISE NOTICE 'Migration 001_add_legislation_mentions completed successfully!';
END $$;
