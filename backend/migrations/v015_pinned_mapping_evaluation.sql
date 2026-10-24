-- Stage 7: pinned evaluation input and private raw/normalized artifacts.
BEGIN;
CREATE TABLE IF NOT EXISTS harness_mapping_artifacts (
 artifact_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES harness_runs(run_id) ON DELETE RESTRICT,
 attempt_id TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES harness_evaluation_jobs(job_id) ON DELETE RESTRICT,
 adapter_id TEXT NOT NULL, adapter_version INTEGER NOT NULL, mapping_digest TEXT NOT NULL,
 artifact_json JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(run_id,attempt_id),
 FOREIGN KEY(adapter_id,adapter_version) REFERENCES harness_adapter_versions(profile_id,version) ON DELETE RESTRICT
);
CREATE OR REPLACE FUNCTION harness_pinned_evaluation_payload() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE actual_digest TEXT;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF OLD.payload_json->>'adapter_id' IS NOT NULL OR NEW.payload_json->>'adapter_id' IS NOT NULL THEN
   IF OLD.payload_json IS DISTINCT FROM NEW.payload_json THEN
    RAISE EXCEPTION 'Pinned evaluation payload is immutable' USING ERRCODE='23514';
   END IF;
  END IF;
 END IF;
 IF NEW.payload_json->>'adapter_id' IS NOT NULL THEN
  SELECT mapping_digest INTO actual_digest FROM harness_adapter_versions
   WHERE profile_id=NEW.payload_json->>'adapter_id'
    AND version=(NEW.payload_json->>'adapter_version')::integer;
  IF actual_digest IS NULL OR actual_digest IS DISTINCT FROM NEW.payload_json->>'adapter_mapping_digest' THEN
   RAISE EXCEPTION 'Evaluation mapping must reference an exact published version' USING ERRCODE='23514';
  END IF;
 ELSIF NEW.payload_json->>'adapter_version' IS NOT NULL OR NEW.payload_json->>'adapter_mapping_digest' IS NOT NULL THEN
  RAISE EXCEPTION 'Incomplete evaluation adapter binding' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
DO $$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='harness_evaluation_jobs'::regclass AND tgname='pinned_evaluation_payload') THEN
  CREATE TRIGGER pinned_evaluation_payload BEFORE INSERT OR UPDATE ON harness_evaluation_jobs
   FOR EACH ROW EXECUTE FUNCTION harness_pinned_evaluation_payload();
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='harness_mapping_artifacts'::regclass AND tgname='mapping_artifacts_immutable') THEN
  CREATE TRIGGER mapping_artifacts_immutable BEFORE UPDATE OR DELETE OR TRUNCATE ON harness_mapping_artifacts
   FOR EACH STATEMENT EXECUTE FUNCTION harness_adapter_append_only();
 END IF;
END $$;
COMMIT;
