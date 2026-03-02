-- Migration 001: Add generated_code and parent_job_id to jobs table
-- For existing databases. New databases get these columns via create_all().

ALTER TABLE jobs ADD COLUMN generated_code TEXT;
ALTER TABLE jobs ADD COLUMN parent_job_id VARCHAR(64);
CREATE INDEX IF NOT EXISTS ix_jobs_parent_job_id ON jobs(parent_job_id);
