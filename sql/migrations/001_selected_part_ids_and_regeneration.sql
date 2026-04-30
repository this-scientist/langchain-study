-- 001: 已有库升级 — selected_part_ids、regeneration_jobs、test_points 溯源列
BEGIN;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'analysis_tasks'
      AND column_name = 'selected_section_ids'
  ) THEN
    ALTER TABLE analysis_tasks RENAME COLUMN selected_section_ids TO selected_part_ids;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS regeneration_jobs (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id               UUID    NOT NULL REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    status                TEXT    NOT NULL DEFAULT 'pending',
    payload               JSONB   NOT NULL,
    progress              JSONB,
    error_message         TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at            TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_regen_task ON regeneration_jobs(task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_regen_status ON regeneration_jobs(status);

ALTER TABLE test_points ADD COLUMN IF NOT EXISTS replaces_id UUID;
ALTER TABLE test_points ADD COLUMN IF NOT EXISTS regeneration_job_id UUID;
ALTER TABLE test_points ADD COLUMN IF NOT EXISTS user_feedback_at_regenerate TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_test_points_replaces_id'
  ) THEN
    ALTER TABLE test_points
      ADD CONSTRAINT fk_test_points_replaces_id
      FOREIGN KEY (replaces_id) REFERENCES test_points(id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_test_points_regeneration_job_id'
  ) THEN
    ALTER TABLE test_points
      ADD CONSTRAINT fk_test_points_regeneration_job_id
      FOREIGN KEY (regeneration_job_id) REFERENCES regeneration_jobs(id) ON DELETE SET NULL;
  END IF;
END $$;

DROP TRIGGER IF EXISTS trg_regeneration_jobs_updated ON regeneration_jobs;
CREATE TRIGGER trg_regeneration_jobs_updated
    BEFORE UPDATE ON regeneration_jobs
    FOR EACH ROW EXECUTE FUNCTION update_timestamp();

COMMIT;
