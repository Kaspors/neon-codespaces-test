-- Simple schema for time registration MVP

CREATE TABLE IF NOT EXISTS users (
  id           BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL,
  email        TEXT UNIQUE NOT NULL,
  role         TEXT NOT NULL CHECK (role IN ('admin','lead','finance','contributor','read-only')),
  active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clients (
  id           BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL,
  currency     TEXT NOT NULL DEFAULT 'EUR',
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
  id              BIGSERIAL PRIMARY KEY,
  client_id       BIGINT NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
  code            TEXT NOT NULL,
  name            TEXT NOT NULL,
  start_date      DATE,
  end_date        DATE,
  budget_hours    NUMERIC(10,2),
  status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('planned','active','closed')),
  approver_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, code)
);

CREATE TABLE IF NOT EXISTS tasks (
  id            BIGSERIAL PRIMARY KEY,
  project_id    BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name          TEXT NOT NULL,
  billable_default BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- who can log time on which projects
CREATE TABLE IF NOT EXISTS project_assignments (
  id         BIGSERIAL PRIMARY KEY,
  project_id BIGINT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  UNIQUE (project_id, user_id)
);

CREATE TABLE IF NOT EXISTS time_entries (
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  project_id  BIGINT NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
  task_id     BIGINT REFERENCES tasks(id) ON DELETE SET NULL,
  work_date   DATE NOT NULL,
  hours       NUMERIC(5,2) NOT NULL CHECK (hours >= 0),
  billable    BOOLEAN NOT NULL DEFAULT TRUE,
  notes       TEXT,
  state       TEXT NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','submitted','approved','rejected')),
  submit_batch_id BIGINT,
  source      TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','timer','import')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_time_entries_user_date ON time_entries(user_id, work_date);
CREATE INDEX IF NOT EXISTS idx_time_entries_project_state ON time_entries(project_id, state);

CREATE TABLE IF NOT EXISTS approvals (
  id            BIGSERIAL PRIMARY KEY,
  time_entry_id BIGINT NOT NULL REFERENCES time_entries(id) ON DELETE CASCADE,
  approver_id   BIGINT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  decision      TEXT NOT NULL CHECK (decision IN ('approve','reject')),
  comment       TEXT,
  decided_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- simple updated_at triggers
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$ LANGUAGE plpgsql;

DO $$ BEGIN
IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'users_touch_updated_at') THEN
  CREATE TRIGGER users_touch_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
END IF;
IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'clients_touch_updated_at') THEN
  CREATE TRIGGER clients_touch_updated_at BEFORE UPDATE ON clients FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
END IF;
IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'projects_touch_updated_at') THEN
  CREATE TRIGGER projects_touch_updated_at BEFORE UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
END IF;
IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'tasks_touch_updated_at') THEN
  CREATE TRIGGER tasks_touch_updated_at BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
END IF;
IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'time_entries_touch_updated_at') THEN
  CREATE TRIGGER time_entries_touch_updated_at BEFORE UPDATE ON time_entries FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
END IF;
END $$;
