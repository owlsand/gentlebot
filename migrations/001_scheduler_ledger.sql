CREATE TABLE scheduled_task (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  guild_id BIGINT,
  channel_id BIGINT,
  owner_user_id BIGINT,
  handler TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('CRON','ONE_SHOT','RRULE','INTERVAL')),
  schedule_expr TEXT NOT NULL,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('shadow','active','paused','canceled')),
  next_run_at TIMESTAMPTZ,
  last_run_at TIMESTAMPTZ,
  last_run_status TEXT,
  concurrency_limit INTEGER NOT NULL DEFAULT 1,
  retry_policy JSONB NOT NULL DEFAULT '{"max_attempts":3,"backoff":"exponential","base_seconds":30}'::jsonb,
  idempotency_scope TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX scheduled_task_active_idx
  ON scheduled_task (is_active) WHERE is_active = TRUE;
CREATE INDEX scheduled_task_next_run_idx
  ON scheduled_task (next_run_at) WHERE is_active = TRUE;

CREATE TABLE task_occurrence (
  id BIGSERIAL PRIMARY KEY,
  task_id BIGINT NOT NULL REFERENCES scheduled_task(id) ON DELETE CASCADE,
  occurrence_key TEXT NOT NULL,
  scheduled_for TIMESTAMPTZ NOT NULL,
  enqueued_at TIMESTAMPTZ,
  state TEXT NOT NULL DEFAULT 'scheduled'
    CHECK (state IN ('scheduled','enqueued','running','executed','failed','canceled','skipped')),
  reason TEXT,
  locked_by TEXT,
  locked_at TIMESTAMPTZ,
  executed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (task_id, occurrence_key)
);

CREATE INDEX task_occurrence_task_time_idx
  ON task_occurrence (task_id, scheduled_for);

CREATE INDEX task_occurrence_executed_idx
  ON task_occurrence (task_id, state)
  WHERE state IN ('executed','failed','skipped');

CREATE TABLE task_execution (
  id BIGSERIAL PRIMARY KEY,
  task_id BIGINT NOT NULL REFERENCES scheduled_task(id) ON DELETE CASCADE,
  occurrence_id BIGINT NOT NULL REFERENCES task_occurrence(id) ON DELETE CASCADE,
  attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
  trigger_type TEXT NOT NULL DEFAULT 'schedule' CHECK (trigger_type IN ('schedule','retry','manual')),
  status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','canceled','timed_out')),
  worker_id TEXT,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  result JSONB,
  error JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (occurrence_id, attempt_no)
);

CREATE INDEX task_execution_finished_idx
  ON task_execution (task_id, finished_at DESC);
