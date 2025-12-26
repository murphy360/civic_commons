-- Migration: Add cascade_triggered_at column to documents table
-- Purpose: Track when cascade has been triggered for a document
-- This allows the cascade_service to avoid re-triggering cascades
-- and to detect when a document has been updated since last cascade

ALTER TABLE documents ADD COLUMN IF NOT EXISTS cascade_triggered_at TIMESTAMP;

-- Index for efficient cascade service queries
CREATE INDEX IF NOT EXISTS idx_documents_cascade_check 
ON documents(id, updated_at, cascade_triggered_at)
WHERE ai_summary IS NOT NULL AND ai_summary != '';
