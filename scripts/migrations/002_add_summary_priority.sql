-- Add summary_priority column for user-initiated priority in AI summary queue
-- When a user clicks "Pending Summary", this is set to NOW() to push the document
-- to the front of the queue

ALTER TABLE documents ADD COLUMN IF NOT EXISTS summary_priority TIMESTAMP;

-- Index for efficient ordering by priority
CREATE INDEX IF NOT EXISTS idx_documents_summary_priority ON documents(summary_priority DESC NULLS LAST);

COMMENT ON COLUMN documents.summary_priority IS 'Timestamp for prioritizing AI summary generation. Higher (more recent) values are processed first.';
