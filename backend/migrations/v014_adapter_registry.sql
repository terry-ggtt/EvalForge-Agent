-- Stage 6, additive manual migration. No Evaluation Job/Run tables are changed.
BEGIN;
CREATE TABLE IF NOT EXISTS harness_adapter_profiles (
 profile_id TEXT PRIMARY KEY, name TEXT NOT NULL CHECK (length(btrim(name))>0),
 description TEXT NOT NULL DEFAULT '', trace_profile_json JSONB NOT NULL,
 next_version INTEGER NOT NULL DEFAULT 1 CHECK (next_version>0),
 created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE IF NOT EXISTS harness_adapter_samples (
 sample_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES harness_adapter_profiles ON DELETE RESTRICT,
 samples_json JSONB NOT NULL CHECK (jsonb_typeof(samples_json)='array'),
 inspection_json JSONB NOT NULL, schema_fingerprint TEXT NOT NULL, sample_digest TEXT NOT NULL,
 created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(sample_id,profile_id)
);
CREATE TABLE IF NOT EXISTS harness_adapter_generations (
 generation_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES harness_adapter_profiles ON DELETE RESTRICT,
 sample_id TEXT NOT NULL, request_json JSONB NOT NULL, budget_json JSONB NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed','needs_manual_review')),
 worker_id TEXT, attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
 lease_expires_at TIMESTAMPTZ, heartbeat_at TIMESTAMPTZ,
 calls_started INTEGER NOT NULL DEFAULT 0 CHECK(calls_started>=0),
 reserved_tokens BIGINT NOT NULL DEFAULT 0 CHECK(reserved_tokens>=0),
 reserved_cost_nano_usd BIGINT NOT NULL DEFAULT 0 CHECK(reserved_cost_nano_usd>=0),
 checkpoints_json JSONB NOT NULL DEFAULT '[]', result_json JSONB, error_code TEXT,
 created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 finished_at TIMESTAMPTZ,
 FOREIGN KEY(sample_id,profile_id) REFERENCES harness_adapter_samples(sample_id,profile_id) ON DELETE RESTRICT,
 UNIQUE(generation_id,profile_id)
);
CREATE INDEX IF NOT EXISTS idx_adapter_generation_queue ON harness_adapter_generations(created_at,generation_id) WHERE status='queued';
CREATE INDEX IF NOT EXISTS idx_adapter_generation_lease ON harness_adapter_generations(lease_expires_at) WHERE status='running';
CREATE TABLE IF NOT EXISTS harness_adapter_candidates (
 candidate_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES harness_adapter_profiles ON DELETE RESTRICT,
 sample_id TEXT NOT NULL, generation_id TEXT UNIQUE,
 mapping_json JSONB NOT NULL, mapping_digest TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','validated','approved','rejected','published')),
 created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(sample_id,profile_id) REFERENCES harness_adapter_samples(sample_id,profile_id) ON DELETE RESTRICT,
 FOREIGN KEY(generation_id,profile_id) REFERENCES harness_adapter_generations(generation_id,profile_id) ON DELETE RESTRICT,
 UNIQUE(candidate_id,profile_id)
);
CREATE TABLE IF NOT EXISTS harness_adapter_validations (
 validation_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL,
 candidate_id TEXT NOT NULL, mapping_digest TEXT NOT NULL, sample_digest TEXT NOT NULL,
 profile_digest TEXT NOT NULL, validator_version TEXT NOT NULL, reports_json JSONB NOT NULL,
 eligible BOOLEAN NOT NULL, evidence_digest TEXT NOT NULL,
 created_by TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(candidate_id,profile_id) REFERENCES harness_adapter_candidates(candidate_id,profile_id) ON DELETE RESTRICT,
 UNIQUE(validation_id,candidate_id,profile_id)
);
CREATE TABLE IF NOT EXISTS harness_adapter_audit (
 audit_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL REFERENCES harness_adapter_profiles ON DELETE RESTRICT,
 candidate_id TEXT, validation_id TEXT, action TEXT NOT NULL,
 actor TEXT NOT NULL, details_json JSONB NOT NULL DEFAULT '{}',
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(candidate_id,profile_id) REFERENCES harness_adapter_candidates(candidate_id,profile_id) ON DELETE RESTRICT,
 FOREIGN KEY(validation_id,candidate_id,profile_id) REFERENCES harness_adapter_validations(validation_id,candidate_id,profile_id) ON DELETE RESTRICT,
 UNIQUE(audit_id,candidate_id,profile_id)
);
CREATE TABLE IF NOT EXISTS harness_adapter_versions (
 profile_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
 candidate_id TEXT NOT NULL UNIQUE, validation_id TEXT NOT NULL, review_id TEXT NOT NULL,
 mapping_json JSONB NOT NULL, mapping_digest TEXT NOT NULL, schema_fingerprint TEXT NOT NULL,
 evidence_digest TEXT NOT NULL, snapshot_json JSONB NOT NULL,
 published_by TEXT NOT NULL, published_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(profile_id,version),
 FOREIGN KEY(candidate_id,profile_id) REFERENCES harness_adapter_candidates(candidate_id,profile_id) ON DELETE RESTRICT,
 FOREIGN KEY(validation_id,candidate_id,profile_id) REFERENCES harness_adapter_validations(validation_id,candidate_id,profile_id) ON DELETE RESTRICT,
 FOREIGN KEY(review_id,candidate_id,profile_id) REFERENCES harness_adapter_audit(audit_id,candidate_id,profile_id) ON DELETE RESTRICT
);
CREATE OR REPLACE FUNCTION harness_adapter_append_only() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Adapter evidence/version records are append-only' USING ERRCODE='23514'; END $$;
CREATE OR REPLACE FUNCTION harness_adapter_candidate_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'UPDATE' THEN
  RAISE EXCEPTION 'Candidate deletion is forbidden' USING ERRCODE='23514';
 END IF;
 IF (to_jsonb(NEW)-'status') IS DISTINCT FROM (to_jsonb(OLD)-'status') THEN
  RAISE EXCEPTION 'Candidate content is immutable' USING ERRCODE='23514';
 END IF;
 IF NOT (
  (OLD.status IN ('draft','validated') AND NEW.status IN ('draft','validated')) OR
  (OLD.status='validated' AND NEW.status IN ('approved','rejected')) OR
  (OLD.status='approved' AND NEW.status='published')
 ) THEN RAISE EXCEPTION 'Invalid candidate transition' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION harness_adapter_profile_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'Profile deletion is forbidden' USING ERRCODE='23514'; END IF;
 IF (to_jsonb(NEW)-'next_version') IS DISTINCT FROM (to_jsonb(OLD)-'next_version')
    OR NEW.next_version<>OLD.next_version+1 THEN
  RAISE EXCEPTION 'Profile configuration is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION harness_adapter_generation_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'Generation deletion is forbidden' USING ERRCODE='23514'; END IF;
 IF OLD.status IN ('completed','failed','needs_manual_review') THEN
  RAISE EXCEPTION 'Terminal generation is immutable' USING ERRCODE='23514';
 END IF;
 IF ROW(NEW.generation_id,NEW.profile_id,NEW.sample_id,NEW.request_json,NEW.budget_json,NEW.created_by,NEW.created_at)
 IS DISTINCT FROM ROW(OLD.generation_id,OLD.profile_id,OLD.sample_id,OLD.request_json,OLD.budget_json,OLD.created_by,OLD.created_at) THEN
  RAISE EXCEPTION 'Generation input is immutable' USING ERRCODE='23514';
 END IF;
 IF NOT ((OLD.status='queued' AND NEW.status='running') OR
         (OLD.status='running' AND NEW.status IN ('running','queued','completed','failed','needs_manual_review'))) THEN
  RAISE EXCEPTION 'Invalid generation transition' USING ERRCODE='23514';
 END IF;
 IF NEW.calls_started<OLD.calls_started OR NEW.reserved_tokens<OLD.reserved_tokens
 OR NEW.reserved_cost_nano_usd<OLD.reserved_cost_nano_usd OR NEW.attempt_count<OLD.attempt_count THEN
  RAISE EXCEPTION 'Generation counters cannot decrease' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
DO $$
DECLARE name TEXT;
BEGIN
 FOREACH name IN ARRAY ARRAY['samples','validations','audit','versions'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass('harness_adapter_'||name) AND tgname='adapter_append_only') THEN
   EXECUTE format('CREATE TRIGGER adapter_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION harness_adapter_append_only()', 'harness_adapter_'||name);
  END IF;
 END LOOP;
 FOREACH name IN ARRAY ARRAY['profiles','candidates','generations'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass('harness_adapter_'||name) AND tgname='adapter_guard') THEN
   EXECUTE format('CREATE TRIGGER adapter_guard BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION %I()', 'harness_adapter_'||name, CASE name WHEN 'profiles' THEN 'harness_adapter_profile_guard' WHEN 'candidates' THEN 'harness_adapter_candidate_guard' ELSE 'harness_adapter_generation_guard' END);
   EXECUTE format('CREATE TRIGGER adapter_no_truncate BEFORE TRUNCATE ON %I FOR EACH STATEMENT EXECUTE FUNCTION harness_adapter_append_only()', 'harness_adapter_'||name);
  END IF;
 END LOOP;
END $$;
COMMIT;
