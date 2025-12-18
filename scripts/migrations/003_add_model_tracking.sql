-- Migration: Add model_used column to track which AI model generated content
-- This allows us to track model performance and regenerate with newer models

-- Add model_used to summaries table
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'summaries' AND column_name = 'model_used'
    ) THEN
        ALTER TABLE summaries ADD COLUMN model_used VARCHAR(64);
        COMMENT ON COLUMN summaries.model_used IS 'AI model used to generate this summary (e.g., gemini-2.0-flash, gemini-2.5-pro)';
    END IF;
END $$;

-- Add model_used to documents table (for ai_summary)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'documents' AND column_name = 'ai_model_used'
    ) THEN
        ALTER TABLE documents ADD COLUMN ai_model_used VARCHAR(64);
        COMMENT ON COLUMN documents.ai_model_used IS 'AI model used to generate the ai_summary (e.g., gemini-2.0-flash)';
    END IF;
END $$;

-- Add model_used to events table (for ai_summary)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'events' AND column_name = 'ai_model_used'
    ) THEN
        ALTER TABLE events ADD COLUMN ai_model_used VARCHAR(64);
        COMMENT ON COLUMN events.ai_model_used IS 'AI model used to generate the ai_summary (e.g., gemini-2.5-flash)';
    END IF;
END $$;
