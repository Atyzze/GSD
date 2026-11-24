-- GSD authoritative schema. One file, applied exactly once to a fresh
-- database. Build 247; edited deliberately at build 429 for the reset onto
-- campaign 2 (see docs/build_notes/BUILD429_NOTES.md): the unfiltered flag
-- became a column of campaign_candidates, and measurements lost the summed
-- geometry-timing column build 415 kept for pre-415 rows. A database created
-- before 429 is refused by the ledger, which is the intended cost.
--
-- Derivation. This is `pg_dump --schema-only` of the database that the 38-step
-- migration chain produced, with the dump preamble, `public.` qualifiers and
-- object comments removed so it applies inside an isolated `folder-schema:`
-- search_path as well as in `public`. Applying this file to an empty database
-- and dumping it again reproduces the chain's dump byte for byte; the check is
-- pinned by tests/integration/test_postgres_isolation.py. The fleet's schema
-- (`agent/evidence/build245_schema.json`) was diffed against the chain's on the
-- same day and was identical: 50 relations plus the ledger table, 38 applied
-- scripts, every checksum matching.
--
-- The chain itself, with the per-build rationale that used to live in its
-- comments, is parked at `attic/schema/migrations_postgres/`. Nothing reads it.
--
-- Ledger. `schema_migrations` is created by the runner, not here, and holds a
-- single row for this file. A database whose ledger still lists the chain is a
-- pre-247 database; the runner refuses it rather than trying to reconcile,
-- because the project has no compatibility path (standing rule 7) and a
-- refusal is a result (rule 4). Resync it fresh.
--
-- Build 513 edited it deliberately for the operator's reset: `engine_decisions_latest`
-- (each law's latest decision, kept by a trigger, so nothing scans the history to
-- find it), no notification on `control` writes, and an index for the checkpoint
-- sweep (see docs/build_notes/BUILD513_NOTES.md). A database from before 513 is
-- refused by the ledger, which is the intended cost.
--
-- Build 521 edited it deliberately for the operator's reset (decision 2C at 520): the chain
-- record beside the compact record (`artifact_retention.record_artifact`, storage class
-- `chain_record`), every proposer draw (`proposal_draws`), each decision's inputs and context
-- (`engine_decisions.inputs_json`, `context_json`), and a law's dynamics axes and reduced basis
-- as columns of `candidate_specs` (see docs/build_notes/BUILD521_NOTES.md).
--
-- Build 529 edited it deliberately for the operator's reset (decision 40, A): the anchors in a
-- table of their own (`anchors`), not JSON rows in `control`; no foreign key, because an anchor
-- outlives its campaign (see docs/build_notes/BUILD529_NOTES.md).

-- Editing. The ledger stores this file's checksum. Change the file and every
-- existing database refuses to start until it is recreated, which is the
-- point: there is exactly one schema and it is this one.

--

-- function gsd_guard_immutable_campaign_definition()

CREATE FUNCTION gsd_guard_immutable_campaign_definition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.campaign_id IS DISTINCT FROM OLD.campaign_id
     OR NEW.spec_json IS DISTINCT FROM OLD.spec_json
     OR NEW.spec_hash IS DISTINCT FROM OLD.spec_hash
     OR NEW.provenance_contract IS DISTINCT FROM OLD.provenance_contract
     OR NEW.campaign_role IS DISTINCT FROM OLD.campaign_role
     OR NEW.parent_campaign_id IS DISTINCT FROM OLD.parent_campaign_id
     OR NEW.campaign_series_id IS DISTINCT FROM OLD.campaign_series_id
     OR NEW.search_seed IS DISTINCT FROM OLD.search_seed
     OR NEW.science_contract_hash IS DISTINCT FROM OLD.science_contract_hash
     OR NEW.search_policy_hash IS DISTINCT FROM OLD.search_policy_hash
     OR NEW.resource_policy_hash IS DISTINCT FROM OLD.resource_policy_hash
     OR NEW.experiment_config_hash IS DISTINCT FROM OLD.experiment_config_hash
     OR NEW.created_build IS DISTINCT FROM OLD.created_build
     OR NEW.created_runtime_fingerprint IS DISTINCT FROM OLD.created_runtime_fingerprint
     OR NEW.change_reason IS DISTINCT FROM OLD.change_reason
     OR NEW.based_on_report_artifact IS DISTINCT FROM OLD.based_on_report_artifact
     OR NEW.based_on_report_sha256 IS DISTINCT FROM OLD.based_on_report_sha256
     OR NEW.created_utc IS DISTINCT FROM OLD.created_utc
  THEN
    RAISE EXCEPTION 'campaign % definition is immutable; create a new campaign', OLD.campaign_id;
  END IF;
  RETURN NEW;
END
$$;

-- function gsd_notify_evidence_rebuild_work()

CREATE FUNCTION gsd_notify_evidence_rebuild_work() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF TG_OP='INSERT' OR OLD.status IS DISTINCT FROM NEW.status THEN
    IF NEW.status IN ('queued','done','failed','cancelled') THEN
      PERFORM pg_notify('gsd_work',json_build_object(
        'table',TG_TABLE_NAME,'op',TG_OP,'status',NEW.status
      )::text);
    END IF;
  END IF;
  RETURN NULL;
END
$$;

-- function gsd_notify_queue_work()

CREATE FUNCTION gsd_notify_queue_work() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF TG_OP='INSERT' THEN
    IF NEW.status='queued' THEN
      PERFORM pg_notify('gsd_work',json_build_object(
        'table',TG_TABLE_NAME,'op',TG_OP,'status',NEW.status
      )::text);
    END IF;
  ELSIF OLD.status IS DISTINCT FROM NEW.status THEN
    IF NEW.status IN ('queued','done','failed','lost','cancelled')
       AND NOT (OLD.status='leased' AND NEW.status='queued') THEN
      PERFORM pg_notify('gsd_work',json_build_object(
        'table',TG_TABLE_NAME,'op',TG_OP,'status',NEW.status
      )::text);
    END IF;
  ELSIF NEW.status='queued' AND OLD.priority IS DISTINCT FROM NEW.priority THEN
    PERFORM pg_notify('gsd_work',json_build_object(
      'table',TG_TABLE_NAME,'op','PRIORITY','status',NEW.status
    )::text);
  END IF;
  RETURN NULL;
END
$$;

-- function gsd_record_candidate_state_history()

CREATE FUNCTION gsd_record_candidate_state_history() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF TG_OP='INSERT' THEN
    INSERT INTO candidate_state_history(
      campaign_id,candidate_id,old_state,new_state,old_reason,new_reason,source,created_utc
    ) VALUES(
      NEW.campaign_id,NEW.candidate_id,NULL,NEW.state,NULL,NEW.state_reason,
      'database_trigger',
      to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
    );
  ELSIF NEW.state IS DISTINCT FROM OLD.state
        OR NEW.state_reason IS DISTINCT FROM OLD.state_reason THEN
    INSERT INTO candidate_state_history(
      campaign_id,candidate_id,old_state,new_state,old_reason,new_reason,source,created_utc
    ) VALUES(
      NEW.campaign_id,NEW.candidate_id,OLD.state,NEW.state,OLD.state_reason,NEW.state_reason,
      'database_trigger',
      to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
    );
  END IF;
  RETURN NEW;
END
$$;

-- function gsd_track_latest_engine_decision()

CREATE FUNCTION gsd_track_latest_engine_decision() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  INSERT INTO engine_decisions_latest(
    campaign_id,candidate_id,decision_id,at_n,next_n,action,rule,reason,priority,
    jobs_created,jobs_seen,facts_json,created_utc
  ) VALUES(
    NEW.campaign_id,NEW.candidate_id,NEW.decision_id,NEW.at_n,NEW.next_n,NEW.action,NEW.rule,
    NEW.reason,NEW.priority,NEW.jobs_created,NEW.jobs_seen,NEW.facts_json,NEW.created_utc
  )
  ON CONFLICT (campaign_id,candidate_id) DO UPDATE SET
    decision_id=EXCLUDED.decision_id,at_n=EXCLUDED.at_n,next_n=EXCLUDED.next_n,
    action=EXCLUDED.action,rule=EXCLUDED.rule,reason=EXCLUDED.reason,priority=EXCLUDED.priority,
    jobs_created=EXCLUDED.jobs_created,jobs_seen=EXCLUDED.jobs_seen,
    facts_json=EXCLUDED.facts_json,created_utc=EXCLUDED.created_utc
  WHERE engine_decisions_latest.decision_id < EXCLUDED.decision_id;
  RETURN NULL;
END
$$;

-- table analysis_attempts

CREATE TABLE analysis_attempts (
    analysis_attempt_id text NOT NULL,
    campaign_id text NOT NULL,
    input_artifact text NOT NULL,
    analysis_version text NOT NULL,
    attempt_number integer NOT NULL,
    owner text,
    claim_token text,
    started_utc text NOT NULL,
    finished_utc text,
    exit_code integer,
    wall_seconds double precision,
    peak_rss_bytes bigint,
    error text,
    error_class text,
    resource_json text DEFAULT '{}'::text NOT NULL,
    build_number integer,
    runtime_fingerprint text,
    peak_uss_bytes bigint,
    peak_pss_bytes bigint,
    memory_reservation_bytes bigint,
    CONSTRAINT analysis_attempts_attempt_number_check CHECK ((attempt_number > 0)),
    CONSTRAINT analysis_attempts_memory_reservation_bytes_check CHECK (((memory_reservation_bytes IS NULL) OR (memory_reservation_bytes >= 0)))
)
WITH (fillfactor='80');

-- table analysis_queue

CREATE TABLE analysis_queue (
    campaign_id text NOT NULL,
    input_artifact text NOT NULL,
    analysis_version text NOT NULL,
    candidate_id text NOT NULL,
    n bigint NOT NULL,
    seed integer NOT NULL,
    producer_job text NOT NULL,
    priority bigint DEFAULT 100 NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    lease_owner text,
    claim_token text,
    lease_expires_utc text,
    error text,
    created_utc text NOT NULL,
    updated_utc text NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 3 NOT NULL,
    next_attempt_utc text,
    error_class text,
    wall_seconds double precision,
    peak_rss_bytes bigint,
    memory_reservation_bytes bigint DEFAULT 0 NOT NULL,
    peak_uss_bytes bigint,
    peak_pss_bytes bigint,
    CONSTRAINT analysis_queue_attempts_check CHECK ((attempts >= 0)),
    CONSTRAINT analysis_queue_max_attempts_check CHECK ((max_attempts > 0)),
    CONSTRAINT analysis_queue_memory_reservation_bytes_check CHECK ((memory_reservation_bytes >= 0)),
    CONSTRAINT analysis_queue_n_check CHECK ((n > 0)),
    CONSTRAINT analysis_queue_peak_pss_bytes_check CHECK (((peak_pss_bytes IS NULL) OR (peak_pss_bytes >= 0))),
    CONSTRAINT analysis_queue_peak_rss_bytes_check CHECK (((peak_rss_bytes IS NULL) OR (peak_rss_bytes >= 0))),
    CONSTRAINT analysis_queue_peak_uss_bytes_check CHECK (((peak_uss_bytes IS NULL) OR (peak_uss_bytes >= 0))),
    CONSTRAINT analysis_queue_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'leased'::text, 'done'::text, 'failed'::text, 'cancelled'::text]))),
    CONSTRAINT analysis_queue_wall_seconds_check CHECK (((wall_seconds IS NULL) OR (wall_seconds >= (0)::double precision)))
)
WITH (fillfactor='70');

-- table analyzer_benchmarks

CREATE TABLE analyzer_benchmarks (
    analysis_version text NOT NULL,
    passed integer NOT NULL,
    report_json text NOT NULL,
    created_utc text NOT NULL,
    runtime_fingerprint text DEFAULT ''::text NOT NULL,
    environment_fingerprint text DEFAULT ''::text NOT NULL,
    CONSTRAINT analyzer_benchmarks_passed_check CHECK ((passed = ANY (ARRAY[0, 1])))
);

-- table anchors

CREATE TABLE anchors (
    candidate_id text NOT NULL,
    campaign_id text,
    status text DEFAULT 'watching'::text NOT NULL,
    document text NOT NULL,
    created_utc text NOT NULL,
    updated_utc text NOT NULL,
    CONSTRAINT anchors_status_check CHECK ((status = ANY (ARRAY['watching'::text, 'probe_around'::text, 'marker'::text])))
);

-- table artifact_producers

CREATE TABLE artifact_producers (
    artifact_hash text NOT NULL,
    job_id text NOT NULL,
    role text NOT NULL,
    created_utc text NOT NULL,
    CONSTRAINT artifact_producers_role_check CHECK ((role = ANY (ARRAY['simulation'::text, 'analysis'::text])))
);

-- table artifact_retention

CREATE TABLE artifact_retention (
    artifact_hash text NOT NULL,
    storage_class text NOT NULL,
    body_state text DEFAULT 'present'::text NOT NULL,
    encoding text DEFAULT 'identity'::text NOT NULL,
    source_artifact text,
    compact_artifact text,
    checkpoint_artifact text,
    record_artifact text,
    evicted_utc text,
    detail_json text DEFAULT '{}'::text NOT NULL,
    created_utc text NOT NULL,
    updated_utc text NOT NULL,
    CONSTRAINT artifact_retention_body_state_check CHECK ((body_state = ANY (ARRAY['present'::text, 'transient'::text, 'evicted'::text]))),
    CONSTRAINT artifact_retention_storage_class_check CHECK ((storage_class = ANY (ARRAY['raw_simulation'::text, 'resume_checkpoint'::text, 'compact_simulation'::text, 'chain_record'::text])))
);

-- table artifacts

CREATE TABLE artifacts (
    artifact_hash text NOT NULL,
    size_bytes bigint NOT NULL,
    media_type text NOT NULL,
    producer_job text,
    meta_json text,
    created_utc text NOT NULL,
    CONSTRAINT artifacts_size_bytes_check CHECK ((size_bytes >= 0))
);

-- table attempts

CREATE TABLE attempts (
    attempt_id text NOT NULL,
    job_id text NOT NULL,
    number integer NOT NULL,
    worker text,
    started_utc text NOT NULL,
    finished_utc text,
    exit_code integer,
    peak_rss_bytes bigint,
    wall_seconds double precision,
    error text,
    user_cpu_seconds double precision,
    system_cpu_seconds double precision,
    peak_uss_bytes bigint,
    peak_pss_bytes bigint,
    peak_vms_bytes bigint,
    peak_edge_count bigint,
    final_edge_count bigint,
    final_mean_degree double precision,
    artifact_bytes bigint,
    resource_json text DEFAULT '{}'::text NOT NULL,
    build_number integer,
    runtime_fingerprint text,
    memory_reservation_bytes bigint,
    error_class text,
    CONSTRAINT attempts_memory_reservation_bytes_check CHECK (((memory_reservation_bytes IS NULL) OR (memory_reservation_bytes >= 0))),
    CONSTRAINT attempts_number_check CHECK ((number > 0))
)
WITH (fillfactor='80');

-- table auxiliary_attempts

CREATE TABLE auxiliary_attempts (
    auxiliary_attempt_id text NOT NULL,
    campaign_id text NOT NULL,
    candidate_id text,
    work_kind text NOT NULL,
    worker text,
    child_pid integer,
    submitted_utc text,
    started_utc text,
    finished_utc text,
    wall_seconds double precision,
    process_cpu_seconds double precision,
    status text NOT NULL,
    metadata_json text DEFAULT '{}'::text NOT NULL,
    build_number integer,
    runtime_fingerprint text,
    CONSTRAINT auxiliary_attempts_process_cpu_seconds_check CHECK (((process_cpu_seconds IS NULL) OR (process_cpu_seconds >= (0)::double precision))),
    CONSTRAINT auxiliary_attempts_wall_seconds_check CHECK (((wall_seconds IS NULL) OR (wall_seconds >= (0)::double precision)))
)
WITH (fillfactor='80');

-- table campaign_archive_candidates

CREATE TABLE campaign_archive_candidates (
    campaign_id text NOT NULL,
    candidate_id text NOT NULL,
    spec_json text NOT NULL,
    dynamics text NOT NULL,
    complexity integer NOT NULL,
    lineage_parent text,
    state text NOT NULL,
    state_reason text,
    summary_json text NOT NULL,
    created_utc text NOT NULL,
    CONSTRAINT campaign_archive_candidates_complexity_check CHECK ((complexity >= 0))
);

-- table campaign_archive_measurements

CREATE TABLE campaign_archive_measurements (
    campaign_id text NOT NULL,
    analysis_id text NOT NULL,
    candidate_id text NOT NULL,
    n bigint NOT NULL,
    seed integer NOT NULL,
    analysis_version text NOT NULL,
    source_artifact text NOT NULL,
    curves_source_artifact text,
    verified integer NOT NULL,
    metrics_json text NOT NULL,
    curve_summary_json text DEFAULT '{}'::text NOT NULL,
    created_utc text NOT NULL,
    CONSTRAINT campaign_archive_measurements_n_check CHECK ((n > 0)),
    CONSTRAINT campaign_archive_measurements_verified_check CHECK ((verified = ANY (ARRAY[0, 1])))
);

-- table campaign_archive_runs

CREATE TABLE campaign_archive_runs (
    campaign_id text NOT NULL,
    job_id text NOT NULL,
    candidate_id text NOT NULL,
    n bigint NOT NULL,
    seed integer NOT NULL,
    replicate integer DEFAULT 0 NOT NULL,
    source_artifact text NOT NULL,
    source_size_bytes bigint NOT NULL,
    verified integer NOT NULL,
    compact_json text NOT NULL,
    created_utc text NOT NULL,
    CONSTRAINT campaign_archive_runs_n_check CHECK ((n > 0)),
    CONSTRAINT campaign_archive_runs_replicate_check CHECK ((replicate >= 0)),
    CONSTRAINT campaign_archive_runs_source_size_bytes_check CHECK ((source_size_bytes >= 0)),
    CONSTRAINT campaign_archive_runs_verified_check CHECK ((verified = ANY (ARRAY[0, 1])))
);

-- table campaign_archives

CREATE TABLE campaign_archives (
    campaign_id text NOT NULL,
    archive_version text NOT NULL,
    state text NOT NULL,
    source_status text NOT NULL,
    spec_json text NOT NULL,
    spec_hash text NOT NULL,
    summary_json text DEFAULT '{}'::text NOT NULL,
    source_db_logical_bytes bigint DEFAULT 0 NOT NULL,
    source_blob_bytes bigint DEFAULT 0 NOT NULL,
    source_blob_count bigint DEFAULT 0 NOT NULL,
    verified_blob_count bigint DEFAULT 0 NOT NULL,
    created_utc text NOT NULL,
    completed_utc text,
    CONSTRAINT campaign_archives_source_blob_bytes_check CHECK ((source_blob_bytes >= 0)),
    CONSTRAINT campaign_archives_source_blob_count_check CHECK ((source_blob_count >= 0)),
    CONSTRAINT campaign_archives_source_db_logical_bytes_check CHECK ((source_db_logical_bytes >= 0)),
    CONSTRAINT campaign_archives_state_check CHECK ((state = ANY (ARRAY['building'::text, 'complete'::text, 'incomplete'::text]))),
    CONSTRAINT campaign_archives_verified_blob_count_check CHECK ((verified_blob_count >= 0))
);

-- sequence gsd_admission_sequence

CREATE SEQUENCE gsd_admission_sequence
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- table campaign_candidates

CREATE TABLE campaign_candidates (
    campaign_id text NOT NULL,
    candidate_id text NOT NULL,
    candidate_number bigint,
    lineage_parent text,
    state text NOT NULL,
    state_reason text,
    created_utc text NOT NULL,
    updated_utc text NOT NULL,
    admission_sequence bigint DEFAULT nextval('gsd_admission_sequence'::regclass) NOT NULL,
    unfiltered boolean DEFAULT false NOT NULL
)
WITH (fillfactor='70');

-- table campaign_events

CREATE TABLE campaign_events (
    campaign_event_id bigint NOT NULL,
    campaign_id text NOT NULL,
    event_type text NOT NULL,
    detail_json text DEFAULT '{}'::text NOT NULL,
    build_number integer,
    runtime_fingerprint text,
    created_utc text NOT NULL
);

-- sequence campaign_events_campaign_event_id_seq

CREATE SEQUENCE campaign_events_campaign_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- sequence owned by campaign_events_campaign_event_id_seq

ALTER SEQUENCE campaign_events_campaign_event_id_seq OWNED BY campaign_events.campaign_event_id;

-- table campaign_graph_counter

CREATE TABLE campaign_graph_counter (
    campaign_id text NOT NULL,
    next_ordinal bigint DEFAULT 1 NOT NULL,
    CONSTRAINT campaign_graph_counter_next_ordinal_check CHECK ((next_ordinal > 0))
);

-- table campaign_links

CREATE TABLE campaign_links (
    child_campaign_id text NOT NULL,
    parent_campaign_id text NOT NULL,
    purpose text NOT NULL,
    channel text NOT NULL,
    created_utc text NOT NULL,
    CONSTRAINT campaign_links_channel_check CHECK ((channel = ANY (ARRAY['merit'::text, 'uncertainty'::text, 'audit'::text, 'manual'::text, 'top-down'::text]))),
    CONSTRAINT campaign_links_purpose_check CHECK ((purpose = ANY (ARRAY['confirmation'::text, 'audit'::text, 'robustness'::text, 'frontier_probe'::text])))
);

-- table campaigns

CREATE TABLE campaigns (
    campaign_id text NOT NULL,
    spec_json text NOT NULL,
    spec_hash text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    workers_target integer,
    created_utc text NOT NULL,
    provenance_contract text,
    campaign_role text DEFAULT 'discovery'::text NOT NULL,
    parent_campaign_id text,
    campaign_series_id text,
    search_seed bigint,
    science_contract_hash text,
    search_policy_hash text,
    resource_policy_hash text,
    experiment_config_hash text,
    created_build integer,
    created_runtime_fingerprint text,
    change_reason text,
    based_on_report_artifact text,
    based_on_report_sha256 text,
    CONSTRAINT campaigns_status_check CHECK ((status = ANY (ARRAY['active'::text, 'closed'::text, 'completed'::text, 'failed'::text, 'archived'::text, 'deleting'::text, 'deleted'::text]))),
    CONSTRAINT campaigns_workers_target_check CHECK (((workers_target IS NULL) OR (workers_target >= 0)))
);

-- table candidate_evidence_rebuilds

CREATE TABLE candidate_evidence_rebuilds (
    campaign_id text NOT NULL,
    candidate_id text NOT NULL,
    analysis_version text NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    requested_measurement_count bigint DEFAULT 0 NOT NULL,
    requested_newest_utc text DEFAULT ''::text NOT NULL,
    built_measurement_count bigint DEFAULT 0 NOT NULL,
    built_newest_utc text DEFAULT ''::text NOT NULL,
    lease_owner text,
    claim_token text,
    lease_expires_utc text,
    attempts integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 8 NOT NULL,
    next_attempt_utc text,
    error text,
    created_utc text NOT NULL,
    updated_utc text NOT NULL,
    CONSTRAINT candidate_evidence_rebuilds_attempts_check CHECK ((attempts >= 0)),
    CONSTRAINT candidate_evidence_rebuilds_built_measurement_count_check CHECK ((built_measurement_count >= 0)),
    CONSTRAINT candidate_evidence_rebuilds_max_attempts_check CHECK ((max_attempts > 0)),
    CONSTRAINT candidate_evidence_rebuilds_requested_measurement_count_check CHECK ((requested_measurement_count >= 0)),
    CONSTRAINT candidate_evidence_rebuilds_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'leased'::text, 'done'::text, 'failed'::text, 'cancelled'::text])))
)
WITH (fillfactor='70');

-- table candidate_specs

CREATE TABLE candidate_specs (
    candidate_id text NOT NULL,
    spec_json text NOT NULL,
    dynamics text NOT NULL,
    complexity integer NOT NULL,
    created_utc text NOT NULL,
    regime text,
    beta double precision,
    locality double precision,
    local_move text,
    zero_temperature boolean,
    swap_share double precision,
    reduced_basis_json text,
    CONSTRAINT candidate_specs_complexity_check CHECK ((complexity >= 0))
);

-- table candidate_state_history

CREATE TABLE candidate_state_history (
    state_event_id bigint NOT NULL,
    campaign_id text NOT NULL,
    candidate_id text NOT NULL,
    old_state text,
    new_state text NOT NULL,
    old_reason text,
    new_reason text,
    source text DEFAULT 'database_trigger'::text NOT NULL,
    created_utc text NOT NULL
);

-- sequence candidate_state_history_state_event_id_seq

CREATE SEQUENCE candidate_state_history_state_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- sequence owned by candidate_state_history_state_event_id_seq

ALTER SEQUENCE candidate_state_history_state_event_id_seq OWNED BY candidate_state_history.state_event_id;

-- view candidates

CREATE VIEW candidates AS
 SELECT cs.candidate_id,
    cc.campaign_id,
    cs.spec_json,
    cs.dynamics,
    cs.complexity,
    cc.lineage_parent,
    cc.state,
    cc.state_reason,
    cc.created_utc,
    cc.updated_utc,
    cc.admission_sequence
   FROM (campaign_candidates cc
     JOIN candidate_specs cs ON ((cs.candidate_id = cc.candidate_id)));

-- table jobs

CREATE TABLE jobs (
    job_id text NOT NULL,
    campaign_id text NOT NULL,
    candidate_id text NOT NULL,
    kind text NOT NULL,
    stage text NOT NULL,
    n bigint NOT NULL,
    seed integer NOT NULL,
    replicate integer DEFAULT 0 NOT NULL,
    spec_json text NOT NULL,
    priority bigint DEFAULT 100 NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    sealed integer DEFAULT 0 NOT NULL,
    lease_owner text,
    lease_expires_utc text,
    attempts integer DEFAULT 0 NOT NULL,
    lease_generation integer DEFAULT 0 NOT NULL,
    result_artifact text,
    error text,
    requested_by text,
    created_utc text NOT NULL,
    updated_utc text NOT NULL,
    memory_reservation_bytes bigint DEFAULT 0 NOT NULL,
    next_attempt_utc text,
    graph_ordinal bigint,
    exec_proposal_locality text GENERATED ALWAYS AS (COALESCE(((spec_json)::jsonb #>> '{execution,proposal_locality}'::text[]), '0'::text)) STORED,
    exec_sampler_audit text GENERATED ALWAYS AS (COALESCE(((spec_json)::jsonb #>> '{execution,sampler_audit_contract}'::text[]), ''::text)) STORED,
    exec_sweeps_multiplier integer GENERATED ALWAYS AS (
CASE
    WHEN (((spec_json)::jsonb #>> '{execution,sweeps_multiplier}'::text[]) ~ '^[0-9]+$'::text) THEN (((spec_json)::jsonb #>> '{execution,sweeps_multiplier}'::text[]))::integer
    ELSE 1
END) STORED,
    exec_resume_artifact text GENERATED ALWAYS AS (((spec_json)::jsonb #>> '{execution,resume_artifact}'::text[])) STORED,
    CONSTRAINT jobs_attempts_check CHECK ((attempts >= 0)),
    CONSTRAINT jobs_kind_check CHECK ((kind = ANY (ARRAY['simulate'::text, 'analyze'::text]))),
    CONSTRAINT jobs_lease_generation_check CHECK ((lease_generation >= 0)),
    CONSTRAINT jobs_memory_reservation_bytes_check CHECK ((memory_reservation_bytes >= 0)),
    CONSTRAINT jobs_n_check CHECK ((n > 0)),
    CONSTRAINT jobs_replicate_check CHECK ((replicate >= 0)),
    CONSTRAINT jobs_sealed_check CHECK ((sealed = ANY (ARRAY[0, 1]))),
    CONSTRAINT jobs_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'leased'::text, 'done'::text, 'failed'::text, 'lost'::text, 'cancelled'::text])))
)
WITH (fillfactor='70');

-- view compute_ledger

CREATE VIEW compute_ledger AS
 SELECT j.campaign_id,
    'simulation'::text AS work_kind,
    j.candidate_id,
    j.n,
    a.worker,
    a.started_utc,
    a.finished_utc,
    a.wall_seconds AS attributed_core_seconds,
    (COALESCE(a.user_cpu_seconds, (0)::double precision) + COALESCE(a.system_cpu_seconds, (0)::double precision)) AS measured_cpu_seconds,
        CASE
            WHEN (a.finished_utc IS NULL) THEN 'running'::text
            WHEN (a.exit_code = 0) THEN 'done'::text
            ELSE 'failed'::text
        END AS status,
    a.build_number,
    a.runtime_fingerprint,
    a.attempt_id AS work_id
   FROM (attempts a
     JOIN jobs j ON ((j.job_id = a.job_id)))
UNION ALL
 SELECT aa.campaign_id,
    'analysis'::text AS work_kind,
    aq.candidate_id,
    aq.n,
    aa.owner AS worker,
    aa.started_utc,
    aa.finished_utc,
    aa.wall_seconds AS attributed_core_seconds,
    NULL::double precision AS measured_cpu_seconds,
        CASE
            WHEN (aa.finished_utc IS NULL) THEN 'running'::text
            WHEN (aa.exit_code = 0) THEN 'done'::text
            ELSE 'failed'::text
        END AS status,
    aa.build_number,
    aa.runtime_fingerprint,
    aa.analysis_attempt_id AS work_id
   FROM (analysis_attempts aa
     JOIN analysis_queue aq ON (((aq.campaign_id = aa.campaign_id) AND (aq.input_artifact = aa.input_artifact) AND (aq.analysis_version = aa.analysis_version))))
UNION ALL
 SELECT ax.campaign_id,
    ax.work_kind,
    ax.candidate_id,
    NULL::bigint AS n,
    ax.worker,
    ax.started_utc,
    ax.finished_utc,
    ax.wall_seconds AS attributed_core_seconds,
    ax.process_cpu_seconds AS measured_cpu_seconds,
    ax.status,
    ax.build_number,
    ax.runtime_fingerprint,
    ax.auxiliary_attempt_id AS work_id
   FROM auxiliary_attempts ax;

-- table control

CREATE TABLE control (
    key text NOT NULL,
    value text
)
WITH (fillfactor='60');

-- table engine_decisions

CREATE TABLE engine_decisions (
    campaign_id text NOT NULL,
    decision_id text NOT NULL,
    candidate_id text NOT NULL,
    at_n bigint,
    next_n bigint,
    action text NOT NULL,
    rule text NOT NULL,
    reason text NOT NULL,
    priority integer,
    queue_order integer,
    jobs_created integer NOT NULL,
    rows_changed integer NOT NULL,
    released_hold boolean NOT NULL,
    jobs_seen text NOT NULL,
    engine text NOT NULL,
    facts_json text NOT NULL,
    created_utc text NOT NULL,
    inputs_json text,
    context_json text,
    CONSTRAINT engine_decisions_pkey PRIMARY KEY (campaign_id, decision_id),
    CONSTRAINT engine_decisions_action_check CHECK ((action = ANY (ARRAY['run_next'::text, 'hold'::text, 'stop'::text, 'done'::text])))
);

CREATE INDEX engine_decisions_law_idx ON engine_decisions USING btree (campaign_id, candidate_id, created_utc);

-- table engine_decisions_latest

CREATE TABLE engine_decisions_latest (
    campaign_id text NOT NULL,
    candidate_id text NOT NULL,
    decision_id text NOT NULL,
    at_n bigint,
    next_n bigint,
    action text NOT NULL,
    rule text NOT NULL,
    reason text NOT NULL,
    priority integer,
    jobs_created integer NOT NULL,
    jobs_seen text NOT NULL,
    facts_json text NOT NULL,
    created_utc text NOT NULL,
    CONSTRAINT engine_decisions_latest_pkey PRIMARY KEY (campaign_id, candidate_id)
);

CREATE INDEX engine_decisions_latest_action ON engine_decisions_latest USING btree (campaign_id, action, rule, next_n);

-- table event_failures

CREATE TABLE event_failures (
    service text NOT NULL,
    event_id bigint NOT NULL,
    attempts integer DEFAULT 1 NOT NULL,
    last_error text NOT NULL,
    updated_utc text NOT NULL
);

-- table events

CREATE TABLE events (
    event_id bigint NOT NULL,
    topic text NOT NULL,
    payload_json text NOT NULL,
    created_utc text NOT NULL
);

-- sequence events_event_id_seq

CREATE SEQUENCE events_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- sequence owned by events_event_id_seq

ALTER SEQUENCE events_event_id_seq OWNED BY events.event_id;

-- table evidence_audits

CREATE TABLE evidence_audits (
    campaign_id text NOT NULL,
    artifact_hash text NOT NULL,
    candidate_id text NOT NULL,
    status text NOT NULL,
    detail_json text NOT NULL,
    audited_utc text NOT NULL
);

-- sequence gsd_phenotype_completion_sequence

CREATE SEQUENCE gsd_phenotype_completion_sequence
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- table four_rung_phenotypes

CREATE TABLE four_rung_phenotypes (
    campaign_id text NOT NULL,
    candidate_id text NOT NULL,
    analysis_version text NOT NULL,
    phenotype_contract text NOT NULL,
    phenotype_json text NOT NULL,
    created_utc text NOT NULL,
    updated_utc text NOT NULL,
    completion_sequence bigint DEFAULT nextval('gsd_phenotype_completion_sequence'::regclass) NOT NULL
);

-- sequence gsd_proposal_sequence

CREATE SEQUENCE gsd_proposal_sequence
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- table infinite_temperature_nulls

CREATE TABLE infinite_temperature_nulls (
    n bigint NOT NULL,
    sampler_contract text NOT NULL,
    analysis_version text NOT NULL,
    result_json text NOT NULL,
    created_utc text NOT NULL,
    updated_utc text NOT NULL,
    CONSTRAINT infinite_temperature_nulls_n_check CHECK ((n > 0))
);

-- table locality_audit_results

CREATE TABLE locality_audit_results (
    campaign_id text NOT NULL,
    candidate_id text NOT NULL,
    analysis_version text NOT NULL,
    audit_contract text NOT NULL,
    result_json text NOT NULL,
    created_utc text NOT NULL,
    updated_utc text NOT NULL
);

-- table measurements

CREATE TABLE measurements (
    campaign_id text NOT NULL,
    analysis_id text NOT NULL,
    candidate_id text NOT NULL,
    n bigint NOT NULL,
    seed integer NOT NULL,
    analysis_version text NOT NULL,
    input_artifact text NOT NULL,
    metrics_json text NOT NULL,
    curves_artifact text,
    created_utc text NOT NULL,
    probe_seconds_d_s double precision,
    probe_seconds_d_v double precision,
    probe_seconds_d_b double precision,
    probe_seconds_d_w double precision,
    CONSTRAINT measurements_n_check CHECK ((n > 0))
);

-- table operational_alerts

CREATE TABLE operational_alerts (
    alert_key text NOT NULL,
    source text NOT NULL,
    severity text NOT NULL,
    category text NOT NULL,
    message text NOT NULL,
    detail_json text DEFAULT '{}'::text NOT NULL,
    first_seen_utc text NOT NULL,
    last_seen_utc text NOT NULL,
    occurrences integer DEFAULT 1 NOT NULL,
    resolved_utc text,
    CONSTRAINT operational_alerts_occurrences_check CHECK ((occurrences > 0)),
    CONSTRAINT operational_alerts_severity_check CHECK ((severity = ANY (ARRAY['warning'::text, 'error'::text])))
);

-- table proposal_assessments

CREATE TABLE proposal_assessments (
    campaign_id text NOT NULL,
    candidate_id text NOT NULL,
    version text NOT NULL,
    source text NOT NULL,
    mode text NOT NULL,
    family_id text NOT NULL,
    score double precision NOT NULL,
    would_admit integer NOT NULL,
    assessment_json text NOT NULL,
    created_utc text NOT NULL,
    CONSTRAINT proposal_assessments_mode_check CHECK ((mode = ANY (ARRAY['off'::text, 'shadow'::text, 'active'::text]))),
    CONSTRAINT proposal_assessments_would_admit_check CHECK ((would_admit = ANY (ARRAY[0, 1])))
);

-- table proposal_draws

CREATE TABLE proposal_draws (
    campaign_id text NOT NULL,
    stream_index bigint NOT NULL,
    draw_index integer NOT NULL,
    outcome text NOT NULL,
    candidate_id text,
    law_json text NOT NULL,
    created_utc text NOT NULL,
    CONSTRAINT proposal_draws_draw_index_check CHECK ((draw_index >= 0))
);

-- table proposal_exposures

CREATE TABLE proposal_exposures (
    campaign_id text NOT NULL,
    event_id text NOT NULL,
    version text NOT NULL,
    pool_id text NOT NULL,
    pool_index integer NOT NULL,
    source text NOT NULL,
    lineage_parent text,
    selected integer NOT NULL,
    candidate_id text,
    dependence_unit_id text NOT NULL,
    dependence_unit_label text NOT NULL,
    coordinates_json text NOT NULL,
    created_utc text NOT NULL,
    proposal_sequence bigint DEFAULT nextval('gsd_proposal_sequence'::regclass) NOT NULL,
    CONSTRAINT proposal_exposures_pool_index_check CHECK ((pool_index >= 0)),
    CONSTRAINT proposal_exposures_selected_check CHECK ((selected = ANY (ARRAY[0, 1])))
);

-- table proposal_policy_epochs

CREATE TABLE proposal_policy_epochs (
    campaign_id text NOT NULL,
    epoch integer NOT NULL,
    policy_version text NOT NULL,
    coupling_targets_json text NOT NULL,
    reason text NOT NULL,
    created_utc text NOT NULL,
    CONSTRAINT proposal_policy_epochs_epoch_check CHECK ((epoch >= 1))
);

-- table read_model_facts

CREATE TABLE read_model_facts (
    fact_table text NOT NULL,
    fact_key text NOT NULL,
    payload_json text NOT NULL,
    updated_utc text NOT NULL
);

-- table read_model_state

CREATE TABLE read_model_state (
    id integer NOT NULL,
    watermark bigint DEFAULT 0 NOT NULL,
    events_applied bigint DEFAULT 0 NOT NULL,
    rebuilt_utc text,
    updated_utc text,
    CONSTRAINT read_model_state_id_check CHECK ((id = 1))
);

-- table report_cycles

CREATE TABLE report_cycles (
    cycle_id text NOT NULL,
    campaign_id text NOT NULL,
    build_number integer,
    started_utc text NOT NULL,
    finished_utc text,
    total_seconds double precision,
    snapshot_seconds double precision,
    report_seconds_json text DEFAULT '{}'::text NOT NULL,
    snapshot_decompressed_bytes bigint,
    api_bytes_transferred bigint,
    trigger_source text,
    cycle_state text
);

-- table resource_calibration_runs

CREATE TABLE resource_calibration_runs (
    calibration_id bigint NOT NULL,
    campaign_id text NOT NULL,
    calibration_contract text NOT NULL,
    build_number integer NOT NULL,
    runtime_fingerprint text NOT NULL,
    environment_fingerprint text NOT NULL,
    started_utc text NOT NULL,
    finished_utc text,
    requested_max_slots integer NOT NULL,
    headroom_fraction double precision NOT NULL,
    max_temperature_celsius double precision,
    safe_max_slots integer,
    target_slots integer,
    safe_peak_watts double precision,
    target_watts double precision,
    stop_reason text,
    status text NOT NULL,
    profile_json text DEFAULT '[]'::text NOT NULL,
    CONSTRAINT resource_calibration_runs_requested_max_slots_check CHECK ((requested_max_slots >= 1))
);

-- sequence resource_calibration_runs_calibration_id_seq

CREATE SEQUENCE resource_calibration_runs_calibration_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- sequence owned by resource_calibration_runs_calibration_id_seq

ALTER SEQUENCE resource_calibration_runs_calibration_id_seq OWNED BY resource_calibration_runs.calibration_id;

-- table resource_governor_events

CREATE TABLE resource_governor_events (
    governor_event_id bigint NOT NULL,
    campaign_id text NOT NULL,
    calibration_id bigint,
    sampled_utc text NOT NULL,
    event_kind text NOT NULL,
    previous_slot_limit integer,
    slot_limit integer NOT NULL,
    reason text NOT NULL,
    detail_json text DEFAULT '{}'::text NOT NULL,
    CONSTRAINT resource_governor_events_slot_limit_check CHECK ((slot_limit >= 0))
);

-- sequence resource_governor_events_governor_event_id_seq

CREATE SEQUENCE resource_governor_events_governor_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- sequence owned by resource_governor_events_governor_event_id_seq

ALTER SEQUENCE resource_governor_events_governor_event_id_seq OWNED BY resource_governor_events.governor_event_id;

-- table resource_telemetry

CREATE TABLE resource_telemetry (
    sample_id bigint NOT NULL,
    campaign_id text NOT NULL,
    telemetry_contract text NOT NULL,
    build_number integer NOT NULL,
    runtime_fingerprint text NOT NULL,
    environment_fingerprint text NOT NULL,
    sampled_utc text NOT NULL,
    phase text NOT NULL,
    interval_seconds double precision,
    cpu_percent double precision,
    gsd_cpu_percent double precision,
    external_cpu_percent_estimate double precision,
    cpu_package_watts double precision,
    cpu_power_limit_watts double precision,
    cpu_temperature_celsius double precision,
    cpu_frequency_mhz double precision,
    memory_total_bytes bigint,
    memory_used_bytes bigint,
    memory_free_bytes bigint,
    memory_bandwidth_json text,
    active_simulations integer DEFAULT 0 NOT NULL,
    active_analyses integer DEFAULT 0 NOT NULL,
    active_work_json text DEFAULT '[]'::text NOT NULL,
    quality text NOT NULL,
    source_json text DEFAULT '{}'::text NOT NULL,
    interval_energy_j double precision,
    active_slot_limit integer,
    governor_phase text,
    calibration_id bigint,
    aggregated_samples integer DEFAULT 1 NOT NULL,
    window_seconds double precision,
    window_started_utc text,
    aggregation_contract text,
    power_samples_json text,
    cpu_temperature_max_celsius double precision,
    CONSTRAINT resource_telemetry_active_analyses_check CHECK ((active_analyses >= 0)),
    CONSTRAINT resource_telemetry_active_simulations_check CHECK ((active_simulations >= 0)),
    CONSTRAINT resource_telemetry_aggregated_samples_check CHECK ((aggregated_samples >= 1)),
    CONSTRAINT resource_telemetry_phase_check CHECK ((phase = ANY (ARRAY['baseline'::text, 'runtime'::text, 'idle'::text])))
)
WITH (autovacuum_vacuum_insert_scale_factor='0.4', autovacuum_vacuum_scale_factor='0.2');

-- sequence resource_telemetry_sample_id_seq

CREATE SEQUENCE resource_telemetry_sample_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- sequence owned by resource_telemetry_sample_id_seq

ALTER SEQUENCE resource_telemetry_sample_id_seq OWNED BY resource_telemetry.sample_id;

-- table rung_diagnostics

CREATE TABLE rung_diagnostics (
    campaign_id text NOT NULL,
    candidate_id text NOT NULL,
    n bigint NOT NULL,
    analysis_version text NOT NULL,
    contract text NOT NULL,
    diagnostics_json text NOT NULL,
    created_utc text NOT NULL,
    CONSTRAINT rung_diagnostics_n_check CHECK ((n > 0))
);

-- table rung_operational_terminals

CREATE TABLE rung_operational_terminals (
    campaign_id text NOT NULL,
    candidate_id text NOT NULL,
    analysis_version text NOT NULL,
    n bigint NOT NULL,
    classification text NOT NULL,
    reason text NOT NULL,
    detail_json text DEFAULT '{}'::text NOT NULL,
    created_utc text NOT NULL,
    updated_utc text NOT NULL,
    CONSTRAINT rung_operational_terminals_n_check CHECK ((n > 0))
);

-- table rung_summaries

CREATE TABLE rung_summaries (
    campaign_id text NOT NULL,
    candidate_id text NOT NULL,
    n bigint NOT NULL,
    analysis_version text NOT NULL,
    summary_json text NOT NULL,
    created_utc text NOT NULL,
    CONSTRAINT rung_summaries_n_check CHECK ((n > 0))
);

-- table scheduler_state

CREATE UNLOGGED TABLE scheduler_state (
    singleton boolean DEFAULT true NOT NULL,
    analysis_version text NOT NULL,
    total_slots integer NOT NULL,
    analysis_slots integer NOT NULL,
    simulation_slots integer NOT NULL,
    analysis_backlog integer NOT NULL,
    queued_simulations integer NOT NULL,
    leased_simulations integer NOT NULL,
    blocked_simulations integer NOT NULL,
    paused boolean DEFAULT false NOT NULL,
    updated_utc text NOT NULL,
    CONSTRAINT scheduler_state_analysis_backlog_check CHECK ((analysis_backlog >= 0)),
    CONSTRAINT scheduler_state_analysis_slots_check CHECK ((analysis_slots >= 0)),
    CONSTRAINT scheduler_state_blocked_simulations_check CHECK ((blocked_simulations >= 0)),
    CONSTRAINT scheduler_state_leased_simulations_check CHECK ((leased_simulations >= 0)),
    CONSTRAINT scheduler_state_queued_simulations_check CHECK ((queued_simulations >= 0)),
    CONSTRAINT scheduler_state_simulation_slots_check CHECK ((simulation_slots >= 0)),
    CONSTRAINT scheduler_state_singleton_check CHECK (singleton),
    CONSTRAINT scheduler_state_total_slots_check CHECK ((total_slots >= 0))
)
WITH (fillfactor='50');

-- table service_cursors

CREATE TABLE service_cursors (
    service text NOT NULL,
    last_event_id bigint NOT NULL
)
WITH (fillfactor='70');

-- table service_heartbeats

CREATE UNLOGGED TABLE service_heartbeats (
    service text NOT NULL,
    pid integer,
    sampled_utc text NOT NULL,
    detail_json text
)
WITH (fillfactor='50');

-- default campaign_events campaign_event_id

ALTER TABLE ONLY campaign_events ALTER COLUMN campaign_event_id SET DEFAULT nextval('campaign_events_campaign_event_id_seq'::regclass);

-- default candidate_state_history state_event_id

ALTER TABLE ONLY candidate_state_history ALTER COLUMN state_event_id SET DEFAULT nextval('candidate_state_history_state_event_id_seq'::regclass);

-- default events event_id

ALTER TABLE ONLY events ALTER COLUMN event_id SET DEFAULT nextval('events_event_id_seq'::regclass);

-- default resource_calibration_runs calibration_id

ALTER TABLE ONLY resource_calibration_runs ALTER COLUMN calibration_id SET DEFAULT nextval('resource_calibration_runs_calibration_id_seq'::regclass);

-- default resource_governor_events governor_event_id

ALTER TABLE ONLY resource_governor_events ALTER COLUMN governor_event_id SET DEFAULT nextval('resource_governor_events_governor_event_id_seq'::regclass);

-- default resource_telemetry sample_id

ALTER TABLE ONLY resource_telemetry ALTER COLUMN sample_id SET DEFAULT nextval('resource_telemetry_sample_id_seq'::regclass);

-- constraint analysis_attempts analysis_attempts_pkey

ALTER TABLE ONLY analysis_attempts
    ADD CONSTRAINT analysis_attempts_pkey PRIMARY KEY (analysis_attempt_id);

-- constraint analysis_queue analysis_queue_pkey

ALTER TABLE ONLY analysis_queue
    ADD CONSTRAINT analysis_queue_pkey PRIMARY KEY (campaign_id, input_artifact, analysis_version);

-- constraint analyzer_benchmarks analyzer_benchmarks_pkey

ALTER TABLE ONLY analyzer_benchmarks
    ADD CONSTRAINT analyzer_benchmarks_pkey PRIMARY KEY (analysis_version);

-- constraint anchors anchors_pkey

ALTER TABLE ONLY anchors
    ADD CONSTRAINT anchors_pkey PRIMARY KEY (candidate_id);

-- constraint artifact_producers artifact_producers_pkey

ALTER TABLE ONLY artifact_producers
    ADD CONSTRAINT artifact_producers_pkey PRIMARY KEY (artifact_hash, job_id, role);

-- constraint artifact_retention artifact_retention_pkey

ALTER TABLE ONLY artifact_retention
    ADD CONSTRAINT artifact_retention_pkey PRIMARY KEY (artifact_hash);

-- constraint artifacts artifacts_pkey

ALTER TABLE ONLY artifacts
    ADD CONSTRAINT artifacts_pkey PRIMARY KEY (artifact_hash);

-- constraint attempts attempts_pkey

ALTER TABLE ONLY attempts
    ADD CONSTRAINT attempts_pkey PRIMARY KEY (attempt_id);

-- constraint auxiliary_attempts auxiliary_attempts_pkey

ALTER TABLE ONLY auxiliary_attempts
    ADD CONSTRAINT auxiliary_attempts_pkey PRIMARY KEY (auxiliary_attempt_id);

-- constraint campaign_archive_candidates campaign_archive_candidates_pkey

ALTER TABLE ONLY campaign_archive_candidates
    ADD CONSTRAINT campaign_archive_candidates_pkey PRIMARY KEY (campaign_id, candidate_id);

-- constraint campaign_archive_measurements campaign_archive_measurements_pkey

ALTER TABLE ONLY campaign_archive_measurements
    ADD CONSTRAINT campaign_archive_measurements_pkey PRIMARY KEY (campaign_id, analysis_id);

-- constraint campaign_archive_runs campaign_archive_runs_pkey

ALTER TABLE ONLY campaign_archive_runs
    ADD CONSTRAINT campaign_archive_runs_pkey PRIMARY KEY (campaign_id, job_id);

-- constraint campaign_archives campaign_archives_pkey

ALTER TABLE ONLY campaign_archives
    ADD CONSTRAINT campaign_archives_pkey PRIMARY KEY (campaign_id);

-- constraint campaign_candidates campaign_candidates_campaign_id_candidate_number_key

ALTER TABLE ONLY campaign_candidates
    ADD CONSTRAINT campaign_candidates_campaign_id_candidate_number_key UNIQUE (campaign_id, candidate_number);

-- constraint campaign_candidates campaign_candidates_pkey

ALTER TABLE ONLY campaign_candidates
    ADD CONSTRAINT campaign_candidates_pkey PRIMARY KEY (campaign_id, candidate_id);

-- constraint campaign_events campaign_events_pkey

ALTER TABLE ONLY campaign_events
    ADD CONSTRAINT campaign_events_pkey PRIMARY KEY (campaign_event_id);

-- constraint campaign_graph_counter campaign_graph_counter_pkey

ALTER TABLE ONLY campaign_graph_counter
    ADD CONSTRAINT campaign_graph_counter_pkey PRIMARY KEY (campaign_id);

-- constraint campaign_links campaign_links_pkey

ALTER TABLE ONLY campaign_links
    ADD CONSTRAINT campaign_links_pkey PRIMARY KEY (child_campaign_id);

-- constraint campaigns campaigns_pkey

ALTER TABLE ONLY campaigns
    ADD CONSTRAINT campaigns_pkey PRIMARY KEY (campaign_id);

-- constraint candidate_evidence_rebuilds candidate_evidence_rebuilds_pkey

ALTER TABLE ONLY candidate_evidence_rebuilds
    ADD CONSTRAINT candidate_evidence_rebuilds_pkey PRIMARY KEY (campaign_id, candidate_id, analysis_version);

-- constraint candidate_specs candidate_specs_pkey

ALTER TABLE ONLY candidate_specs
    ADD CONSTRAINT candidate_specs_pkey PRIMARY KEY (candidate_id);

-- constraint candidate_state_history candidate_state_history_pkey

ALTER TABLE ONLY candidate_state_history
    ADD CONSTRAINT candidate_state_history_pkey PRIMARY KEY (state_event_id);

-- constraint control control_pkey

ALTER TABLE ONLY control
    ADD CONSTRAINT control_pkey PRIMARY KEY (key);

-- constraint event_failures event_failures_pkey

ALTER TABLE ONLY event_failures
    ADD CONSTRAINT event_failures_pkey PRIMARY KEY (service, event_id);

-- constraint events events_pkey

ALTER TABLE ONLY events
    ADD CONSTRAINT events_pkey PRIMARY KEY (event_id);

-- constraint evidence_audits evidence_audits_pkey

ALTER TABLE ONLY evidence_audits
    ADD CONSTRAINT evidence_audits_pkey PRIMARY KEY (campaign_id, artifact_hash);

-- constraint four_rung_phenotypes four_rung_phenotypes_pkey

ALTER TABLE ONLY four_rung_phenotypes
    ADD CONSTRAINT four_rung_phenotypes_pkey PRIMARY KEY (campaign_id, candidate_id, analysis_version);

-- constraint infinite_temperature_nulls infinite_temperature_nulls_pkey

ALTER TABLE ONLY infinite_temperature_nulls
    ADD CONSTRAINT infinite_temperature_nulls_pkey PRIMARY KEY (n, sampler_contract, analysis_version);

-- constraint jobs jobs_pkey

ALTER TABLE ONLY jobs
    ADD CONSTRAINT jobs_pkey PRIMARY KEY (job_id);

-- constraint locality_audit_results locality_audit_results_pkey

ALTER TABLE ONLY locality_audit_results
    ADD CONSTRAINT locality_audit_results_pkey PRIMARY KEY (campaign_id, candidate_id, analysis_version);

-- constraint measurements measurements_pkey

ALTER TABLE ONLY measurements
    ADD CONSTRAINT measurements_pkey PRIMARY KEY (campaign_id, analysis_id);

-- constraint operational_alerts operational_alerts_pkey

ALTER TABLE ONLY operational_alerts
    ADD CONSTRAINT operational_alerts_pkey PRIMARY KEY (alert_key);

-- constraint proposal_assessments proposal_assessments_pkey

ALTER TABLE ONLY proposal_assessments
    ADD CONSTRAINT proposal_assessments_pkey PRIMARY KEY (campaign_id, candidate_id, version);

-- constraint proposal_draws proposal_draws_pkey

ALTER TABLE ONLY proposal_draws
    ADD CONSTRAINT proposal_draws_pkey PRIMARY KEY (campaign_id, stream_index, draw_index);

-- constraint proposal_exposures proposal_exposures_campaign_id_pool_id_pool_index_key

ALTER TABLE ONLY proposal_exposures
    ADD CONSTRAINT proposal_exposures_campaign_id_pool_id_pool_index_key UNIQUE (campaign_id, pool_id, pool_index);

-- constraint proposal_exposures proposal_exposures_pkey

ALTER TABLE ONLY proposal_exposures
    ADD CONSTRAINT proposal_exposures_pkey PRIMARY KEY (campaign_id, event_id);

-- constraint proposal_policy_epochs proposal_policy_epochs_campaign_id_policy_version_key

ALTER TABLE ONLY proposal_policy_epochs
    ADD CONSTRAINT proposal_policy_epochs_campaign_id_policy_version_key UNIQUE (campaign_id, policy_version);

-- constraint proposal_policy_epochs proposal_policy_epochs_pkey

ALTER TABLE ONLY proposal_policy_epochs
    ADD CONSTRAINT proposal_policy_epochs_pkey PRIMARY KEY (campaign_id, epoch);

-- constraint read_model_facts read_model_facts_pkey

ALTER TABLE ONLY read_model_facts
    ADD CONSTRAINT read_model_facts_pkey PRIMARY KEY (fact_table, fact_key);

-- constraint read_model_state read_model_state_pkey

ALTER TABLE ONLY read_model_state
    ADD CONSTRAINT read_model_state_pkey PRIMARY KEY (id);

-- constraint report_cycles report_cycles_pkey

ALTER TABLE ONLY report_cycles
    ADD CONSTRAINT report_cycles_pkey PRIMARY KEY (cycle_id);

-- constraint resource_calibration_runs resource_calibration_runs_pkey

ALTER TABLE ONLY resource_calibration_runs
    ADD CONSTRAINT resource_calibration_runs_pkey PRIMARY KEY (calibration_id);

-- constraint resource_governor_events resource_governor_events_pkey

ALTER TABLE ONLY resource_governor_events
    ADD CONSTRAINT resource_governor_events_pkey PRIMARY KEY (governor_event_id);

-- constraint resource_telemetry resource_telemetry_pkey

ALTER TABLE ONLY resource_telemetry
    ADD CONSTRAINT resource_telemetry_pkey PRIMARY KEY (sample_id);

-- constraint rung_diagnostics rung_diagnostics_pkey

ALTER TABLE ONLY rung_diagnostics
    ADD CONSTRAINT rung_diagnostics_pkey PRIMARY KEY (campaign_id, candidate_id, n, analysis_version);

-- constraint rung_operational_terminals rung_operational_terminals_pkey

ALTER TABLE ONLY rung_operational_terminals
    ADD CONSTRAINT rung_operational_terminals_pkey PRIMARY KEY (campaign_id, candidate_id, analysis_version, n);

-- constraint rung_summaries rung_summaries_pkey

ALTER TABLE ONLY rung_summaries
    ADD CONSTRAINT rung_summaries_pkey PRIMARY KEY (campaign_id, candidate_id, n, analysis_version);

-- constraint scheduler_state scheduler_state_pkey

ALTER TABLE ONLY scheduler_state
    ADD CONSTRAINT scheduler_state_pkey PRIMARY KEY (singleton);

-- constraint service_cursors service_cursors_pkey

ALTER TABLE ONLY service_cursors
    ADD CONSTRAINT service_cursors_pkey PRIMARY KEY (service);

-- constraint service_heartbeats service_heartbeats_pkey

ALTER TABLE ONLY service_heartbeats
    ADD CONSTRAINT service_heartbeats_pkey PRIMARY KEY (service);

-- index analysis_attempts_artifact

CREATE INDEX analysis_attempts_artifact ON analysis_attempts USING btree (campaign_id, input_artifact, analysis_version, attempt_number);

-- index analysis_attempts_campaign

CREATE INDEX analysis_attempts_campaign ON analysis_attempts USING btree (campaign_id, started_utc);

-- index analysis_queue_campaign_status_n
--
-- Build 411. `analysis_backlog` and the fleet ladder both filter a campaign by
-- live status and group by N. The campaign-prefix index made them walk every
-- entry for that campaign -- roughly 97k on campaign 5 for a few hundred live
-- rows -- and build 409 declined to add this because `schema.sql` has no
-- in-place upgrade and an edit strands every live database. A reinitialise
-- makes it free, and this is the one moment it is.

CREATE INDEX analysis_queue_campaign_status_n ON analysis_queue USING btree (campaign_id, status, n);

-- index analysis_queue_campaign_candidate

CREATE INDEX analysis_queue_campaign_candidate ON analysis_queue USING btree (campaign_id, candidate_id, status);

-- index analysis_queue_candidate

CREATE INDEX analysis_queue_candidate ON analysis_queue USING btree (campaign_id, candidate_id, analysis_version, status, n);

-- index analysis_queue_claim

CREATE INDEX analysis_queue_claim ON analysis_queue USING btree (analysis_version, priority, updated_utc, input_artifact) WHERE (status = 'queued'::text);

-- index analysis_queue_input_artifact

CREATE INDEX analysis_queue_input_artifact ON analysis_queue USING btree (input_artifact);

-- index analysis_queue_producer_job_fk

CREATE INDEX analysis_queue_producer_job_fk ON analysis_queue USING btree (producer_job);

-- index analysis_queue_retry_claim

CREATE INDEX analysis_queue_retry_claim ON analysis_queue USING btree (analysis_version, priority, next_attempt_utc, updated_utc, input_artifact) WHERE (status = 'queued'::text);

-- index analysis_queue_runtime_profile

CREATE INDEX analysis_queue_runtime_profile ON analysis_queue USING btree (n, wall_seconds) WHERE ((status = 'done'::text) AND (wall_seconds IS NOT NULL));

-- index analysis_queue_version_status

CREATE INDEX analysis_queue_version_status ON analysis_queue USING btree (analysis_version, status);

-- index anchors_created

CREATE INDEX anchors_created ON anchors USING btree (created_utc);

-- index artifact_producers_job

CREATE INDEX artifact_producers_job ON artifact_producers USING btree (job_id, artifact_hash);

-- index artifact_retention_checkpoint

CREATE INDEX artifact_retention_checkpoint ON artifact_retention USING btree (checkpoint_artifact) WHERE (checkpoint_artifact IS NOT NULL);

-- index artifact_retention_compact

CREATE INDEX artifact_retention_compact ON artifact_retention USING btree (compact_artifact) WHERE (compact_artifact IS NOT NULL);

-- index artifact_retention_source

CREATE INDEX artifact_retention_source ON artifact_retention USING btree (source_artifact);

-- index artifact_retention_state

CREATE INDEX artifact_retention_state ON artifact_retention USING btree (storage_class, body_state, updated_utc);

-- index artifacts_producer_job_fk

CREATE INDEX artifacts_producer_job_fk ON artifacts USING btree (producer_job) WHERE (producer_job IS NOT NULL);

-- index attempts_job_fk

CREATE INDEX attempts_job_fk ON attempts USING btree (job_id);

-- index auxiliary_attempts_campaign_time

CREATE INDEX auxiliary_attempts_campaign_time ON auxiliary_attempts USING btree (campaign_id, started_utc, auxiliary_attempt_id);

-- index auxiliary_attempts_kind

CREATE INDEX auxiliary_attempts_kind ON auxiliary_attempts USING btree (campaign_id, work_kind, started_utc);

-- index campaign_archive_candidates_state

CREATE INDEX campaign_archive_candidates_state ON campaign_archive_candidates USING btree (campaign_id, state, candidate_id);

-- index campaign_archive_measurements_candidate

CREATE INDEX campaign_archive_measurements_candidate ON campaign_archive_measurements USING btree (campaign_id, candidate_id, analysis_version, n, seed);

-- index campaign_archive_runs_candidate

CREATE INDEX campaign_archive_runs_candidate ON campaign_archive_runs USING btree (campaign_id, candidate_id, n, seed);

-- index campaign_candidates_admission_sequence

CREATE INDEX campaign_candidates_admission_sequence ON campaign_candidates USING btree (campaign_id, admission_sequence, candidate_id);

-- index campaign_candidates_candidate_fk

CREATE INDEX campaign_candidates_candidate_fk ON campaign_candidates USING btree (candidate_id);

-- index campaign_candidates_lineage_parent_fk

CREATE INDEX campaign_candidates_lineage_parent_fk ON campaign_candidates USING btree (lineage_parent) WHERE (lineage_parent IS NOT NULL);

-- index campaign_candidates_state

CREATE INDEX campaign_candidates_state ON campaign_candidates USING btree (campaign_id, state, created_utc);

-- index campaign_candidates_unfiltered

CREATE INDEX campaign_candidates_unfiltered ON campaign_candidates USING btree (campaign_id) WHERE unfiltered;

-- index campaign_events_campaign_time

CREATE INDEX campaign_events_campaign_time ON campaign_events USING btree (campaign_id, created_utc, campaign_event_id);

-- index campaign_links_parent

CREATE INDEX campaign_links_parent ON campaign_links USING btree (parent_campaign_id, purpose, channel);

-- index campaigns_parent

CREATE INDEX campaigns_parent ON campaigns USING btree (parent_campaign_id, created_utc, campaign_id);

-- index campaigns_search_policy

CREATE INDEX campaigns_search_policy ON campaigns USING btree (search_policy_hash, created_utc, campaign_id);

-- index campaigns_series

CREATE INDEX campaigns_series ON campaigns USING btree (campaign_series_id, created_utc, campaign_id);

-- index candidate_evidence_rebuild_claim

CREATE INDEX candidate_evidence_rebuild_claim ON candidate_evidence_rebuilds USING btree (analysis_version, next_attempt_utc, updated_utc, candidate_id) WHERE (status = 'queued'::text);

-- index candidate_evidence_rebuild_lease

CREATE INDEX candidate_evidence_rebuild_lease ON candidate_evidence_rebuilds USING btree (lease_expires_utc) WHERE (status = 'leased'::text);

-- index candidate_evidence_rebuild_status

CREATE INDEX candidate_evidence_rebuild_status ON candidate_evidence_rebuilds USING btree (campaign_id, status, analysis_version);

-- index candidate_state_history_campaign

CREATE INDEX candidate_state_history_campaign ON candidate_state_history USING btree (campaign_id, state_event_id, candidate_id);

-- index candidate_state_history_candidate

CREATE INDEX candidate_state_history_candidate ON candidate_state_history USING btree (campaign_id, candidate_id, state_event_id);

-- index event_failures_event_fk

CREATE INDEX event_failures_event_fk ON event_failures USING btree (event_id);

-- index evidence_audits_artifact_fk

CREATE INDEX evidence_audits_artifact_fk ON evidence_audits USING btree (artifact_hash);

-- index evidence_audits_candidate

CREATE INDEX evidence_audits_candidate ON evidence_audits USING btree (campaign_id, candidate_id, status, audited_utc);

-- index four_rung_phenotypes_campaign

CREATE INDEX four_rung_phenotypes_campaign ON four_rung_phenotypes USING btree (campaign_id, updated_utc, candidate_id);

-- index four_rung_phenotypes_completion_sequence

CREATE INDEX four_rung_phenotypes_completion_sequence ON four_rung_phenotypes USING btree (campaign_id, completion_sequence, candidate_id);

-- index idx_jobs_graph_ordinal

CREATE UNIQUE INDEX idx_jobs_graph_ordinal ON jobs USING btree (campaign_id, graph_ordinal) WHERE (graph_ordinal IS NOT NULL);

-- index idx_jobs_ordinal_lookup

CREATE INDEX idx_jobs_ordinal_lookup ON jobs USING btree (campaign_id, candidate_id, n) WHERE (graph_ordinal IS NOT NULL);

-- index jobs_analysis_source

CREATE INDEX jobs_analysis_source ON jobs USING btree (updated_utc, job_id) INCLUDE (campaign_id, candidate_id, n, seed, result_artifact) WHERE ((kind = 'simulate'::text) AND (status = 'done'::text) AND (result_artifact IS NOT NULL));

-- index jobs_campaign_candidate

CREATE INDEX jobs_campaign_candidate ON jobs USING btree (campaign_id, candidate_id, status);

-- index jobs_campaign_status

CREATE INDEX jobs_campaign_status ON jobs USING btree (campaign_id, status, n);

-- index jobs_claimable_retry_idx

CREATE INDEX jobs_claimable_retry_idx ON jobs USING btree (status, kind, next_attempt_utc, priority, created_utc, job_id) WHERE (status = 'queued'::text);

-- index jobs_queue

CREATE INDEX jobs_queue ON jobs USING btree (status, kind, priority, created_utc);

-- index jobs_result_artifact

CREATE INDEX jobs_result_artifact ON jobs USING btree (result_artifact) WHERE (result_artifact IS NOT NULL);

-- index jobs_simulation_claim

CREATE INDEX jobs_simulation_claim ON jobs USING btree (priority, created_utc, job_id) WHERE ((kind = 'simulate'::text) AND (status = 'queued'::text));

-- index locality_audit_results_campaign

CREATE INDEX locality_audit_results_campaign ON locality_audit_results USING btree (campaign_id, updated_utc, candidate_id);

-- index meas_cand

CREATE INDEX meas_cand ON measurements USING btree (campaign_id, candidate_id, analysis_version, n, seed);

-- index measurements_curves_artifact

CREATE INDEX measurements_curves_artifact ON measurements USING btree (curves_artifact) WHERE (curves_artifact IS NOT NULL);

-- index measurements_input_artifact

CREATE INDEX measurements_input_artifact ON measurements USING btree (input_artifact);

-- index measurements_input_lookup

CREATE INDEX measurements_input_lookup ON measurements USING btree (campaign_id, input_artifact, analysis_version);

-- index operational_alerts_active

CREATE INDEX operational_alerts_active ON operational_alerts USING btree (severity, last_seen_utc, alert_key) WHERE (resolved_utc IS NULL);

-- index proposal_assessments_family

CREATE INDEX proposal_assessments_family ON proposal_assessments USING btree (campaign_id, family_id, created_utc);

-- index proposal_exposures_candidate

CREATE INDEX proposal_exposures_candidate ON proposal_exposures USING btree (campaign_id, candidate_id, created_utc);

-- index proposal_exposures_sequence

CREATE INDEX proposal_exposures_sequence ON proposal_exposures USING btree (campaign_id, proposal_sequence, event_id);

-- index proposal_exposures_unit

CREATE INDEX proposal_exposures_unit ON proposal_exposures USING btree (campaign_id, version, dependence_unit_id, created_utc);

-- index proposal_policy_epochs_campaign_created

CREATE INDEX proposal_policy_epochs_campaign_created ON proposal_policy_epochs USING btree (campaign_id, created_utc, epoch);

-- index read_model_facts_by_table

CREATE INDEX read_model_facts_by_table ON read_model_facts USING btree (fact_table);

-- index report_cycles_by_campaign_started

CREATE INDEX report_cycles_by_campaign_started ON report_cycles USING btree (campaign_id, started_utc DESC);

-- index report_cycles_completed

CREATE INDEX report_cycles_completed ON report_cycles USING btree (campaign_id, finished_utc DESC) WHERE ((finished_utc IS NOT NULL) AND (total_seconds IS NOT NULL));

-- index resource_calibration_campaign_time

CREATE INDEX resource_calibration_campaign_time ON resource_calibration_runs USING btree (campaign_id, started_utc, calibration_id);

-- index resource_governor_campaign_time

CREATE INDEX resource_governor_campaign_time ON resource_governor_events USING btree (campaign_id, sampled_utc, governor_event_id);

-- index resource_telemetry_campaign_time

CREATE INDEX resource_telemetry_campaign_time ON resource_telemetry USING btree (campaign_id, sampled_utc, sample_id);

-- index resource_telemetry_phase_time

CREATE INDEX resource_telemetry_phase_time ON resource_telemetry USING btree (campaign_id, phase, sampled_utc);

-- index rung_operational_terminals_candidate

CREATE INDEX rung_operational_terminals_candidate ON rung_operational_terminals USING btree (campaign_id, candidate_id, analysis_version, n);

-- trigger campaign_candidates campaign_candidates_state_history

CREATE TRIGGER campaign_candidates_state_history AFTER INSERT OR UPDATE OF state, state_reason ON campaign_candidates FOR EACH ROW EXECUTE FUNCTION gsd_record_candidate_state_history();

-- trigger campaigns campaigns_immutable_definition

CREATE TRIGGER campaigns_immutable_definition BEFORE UPDATE ON campaigns FOR EACH ROW EXECUTE FUNCTION gsd_guard_immutable_campaign_definition();

-- trigger analysis_queue gsd_analysis_work_notify

CREATE TRIGGER gsd_analysis_work_notify AFTER INSERT OR UPDATE OF status, priority ON analysis_queue FOR EACH ROW EXECUTE FUNCTION gsd_notify_queue_work();

-- trigger engine_decisions gsd_engine_decisions_latest

CREATE TRIGGER gsd_engine_decisions_latest AFTER INSERT ON engine_decisions FOR EACH ROW EXECUTE FUNCTION gsd_track_latest_engine_decision();

-- trigger candidate_evidence_rebuilds gsd_evidence_rebuild_work_notify

CREATE TRIGGER gsd_evidence_rebuild_work_notify AFTER INSERT OR UPDATE OF status ON candidate_evidence_rebuilds FOR EACH ROW EXECUTE FUNCTION gsd_notify_evidence_rebuild_work();

-- trigger jobs gsd_jobs_work_notify

CREATE TRIGGER gsd_jobs_work_notify AFTER INSERT OR UPDATE OF status, result_artifact, priority ON jobs FOR EACH ROW EXECUTE FUNCTION gsd_notify_queue_work();

-- fk constraint analysis_attempts analysis_attempts_campaign_id_input_artifact_analysis_vers_fkey

ALTER TABLE ONLY analysis_attempts
    ADD CONSTRAINT analysis_attempts_campaign_id_input_artifact_analysis_vers_fkey FOREIGN KEY (campaign_id, input_artifact, analysis_version) REFERENCES analysis_queue(campaign_id, input_artifact, analysis_version) ON DELETE CASCADE;

-- fk constraint analysis_queue analysis_queue_campaign_id_candidate_id_fkey

ALTER TABLE ONLY analysis_queue
    ADD CONSTRAINT analysis_queue_campaign_id_candidate_id_fkey FOREIGN KEY (campaign_id, candidate_id) REFERENCES campaign_candidates(campaign_id, candidate_id) ON DELETE CASCADE;

-- fk constraint analysis_queue analysis_queue_campaign_id_fkey

ALTER TABLE ONLY analysis_queue
    ADD CONSTRAINT analysis_queue_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint analysis_queue analysis_queue_input_artifact_fkey

ALTER TABLE ONLY analysis_queue
    ADD CONSTRAINT analysis_queue_input_artifact_fkey FOREIGN KEY (input_artifact) REFERENCES artifacts(artifact_hash) ON DELETE CASCADE;

-- fk constraint analysis_queue analysis_queue_producer_job_fkey

ALTER TABLE ONLY analysis_queue
    ADD CONSTRAINT analysis_queue_producer_job_fkey FOREIGN KEY (producer_job) REFERENCES jobs(job_id) ON DELETE CASCADE;

-- fk constraint artifact_producers artifact_producers_artifact_hash_fkey

ALTER TABLE ONLY artifact_producers
    ADD CONSTRAINT artifact_producers_artifact_hash_fkey FOREIGN KEY (artifact_hash) REFERENCES artifacts(artifact_hash) ON DELETE CASCADE;

-- fk constraint artifact_producers artifact_producers_job_id_fkey

ALTER TABLE ONLY artifact_producers
    ADD CONSTRAINT artifact_producers_job_id_fkey FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;

-- fk constraint artifact_retention artifact_retention_artifact_hash_fkey

ALTER TABLE ONLY artifact_retention
    ADD CONSTRAINT artifact_retention_artifact_hash_fkey FOREIGN KEY (artifact_hash) REFERENCES artifacts(artifact_hash) ON DELETE CASCADE;

-- fk constraint artifact_retention artifact_retention_checkpoint_artifact_fkey

ALTER TABLE ONLY artifact_retention
    ADD CONSTRAINT artifact_retention_checkpoint_artifact_fkey FOREIGN KEY (checkpoint_artifact) REFERENCES artifacts(artifact_hash) ON DELETE SET NULL;

-- fk constraint artifact_retention artifact_retention_compact_artifact_fkey

ALTER TABLE ONLY artifact_retention
    ADD CONSTRAINT artifact_retention_compact_artifact_fkey FOREIGN KEY (compact_artifact) REFERENCES artifacts(artifact_hash) ON DELETE SET NULL;

-- fk constraint artifacts artifacts_producer_job_fkey

ALTER TABLE ONLY artifacts
    ADD CONSTRAINT artifacts_producer_job_fkey FOREIGN KEY (producer_job) REFERENCES jobs(job_id) ON DELETE SET NULL;

-- fk constraint attempts attempts_job_id_fkey

ALTER TABLE ONLY attempts
    ADD CONSTRAINT attempts_job_id_fkey FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE;

-- fk constraint auxiliary_attempts auxiliary_attempts_campaign_id_fkey

ALTER TABLE ONLY auxiliary_attempts
    ADD CONSTRAINT auxiliary_attempts_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint campaign_archive_candidates campaign_archive_candidates_campaign_id_fkey

ALTER TABLE ONLY campaign_archive_candidates
    ADD CONSTRAINT campaign_archive_candidates_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaign_archives(campaign_id) ON DELETE CASCADE;

-- fk constraint campaign_archive_measurements campaign_archive_measurements_campaign_id_fkey

ALTER TABLE ONLY campaign_archive_measurements
    ADD CONSTRAINT campaign_archive_measurements_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaign_archives(campaign_id) ON DELETE CASCADE;

-- fk constraint campaign_archive_runs campaign_archive_runs_campaign_id_fkey

ALTER TABLE ONLY campaign_archive_runs
    ADD CONSTRAINT campaign_archive_runs_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaign_archives(campaign_id) ON DELETE CASCADE;

-- fk constraint campaign_candidates campaign_candidates_campaign_id_fkey

ALTER TABLE ONLY campaign_candidates
    ADD CONSTRAINT campaign_candidates_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint campaign_candidates campaign_candidates_candidate_id_fkey

ALTER TABLE ONLY campaign_candidates
    ADD CONSTRAINT campaign_candidates_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES candidate_specs(candidate_id) ON DELETE RESTRICT;

-- fk constraint campaign_candidates campaign_candidates_lineage_parent_fkey

ALTER TABLE ONLY campaign_candidates
    ADD CONSTRAINT campaign_candidates_lineage_parent_fkey FOREIGN KEY (lineage_parent) REFERENCES candidate_specs(candidate_id) ON DELETE SET NULL;

-- fk constraint campaign_events campaign_events_campaign_id_fkey

ALTER TABLE ONLY campaign_events
    ADD CONSTRAINT campaign_events_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint campaign_graph_counter campaign_graph_counter_campaign_id_fkey

ALTER TABLE ONLY campaign_graph_counter
    ADD CONSTRAINT campaign_graph_counter_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint campaign_links campaign_links_child_campaign_id_fkey

ALTER TABLE ONLY campaign_links
    ADD CONSTRAINT campaign_links_child_campaign_id_fkey FOREIGN KEY (child_campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint campaign_links campaign_links_parent_campaign_id_fkey

ALTER TABLE ONLY campaign_links
    ADD CONSTRAINT campaign_links_parent_campaign_id_fkey FOREIGN KEY (parent_campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint campaigns campaigns_parent_campaign_fk

ALTER TABLE ONLY campaigns
    ADD CONSTRAINT campaigns_parent_campaign_fk FOREIGN KEY (parent_campaign_id) REFERENCES campaigns(campaign_id) ON DELETE RESTRICT;

-- fk constraint campaigns campaigns_report_artifact_fk

ALTER TABLE ONLY campaigns
    ADD CONSTRAINT campaigns_report_artifact_fk FOREIGN KEY (based_on_report_artifact) REFERENCES artifacts(artifact_hash) ON DELETE RESTRICT;

-- fk constraint candidate_evidence_rebuilds candidate_evidence_rebuilds_campaign_id_candidate_id_fkey

ALTER TABLE ONLY candidate_evidence_rebuilds
    ADD CONSTRAINT candidate_evidence_rebuilds_campaign_id_candidate_id_fkey FOREIGN KEY (campaign_id, candidate_id) REFERENCES campaign_candidates(campaign_id, candidate_id) ON DELETE CASCADE;

-- fk constraint candidate_state_history candidate_state_history_campaign_id_candidate_id_fkey

ALTER TABLE ONLY candidate_state_history
    ADD CONSTRAINT candidate_state_history_campaign_id_candidate_id_fkey FOREIGN KEY (campaign_id, candidate_id) REFERENCES campaign_candidates(campaign_id, candidate_id) ON DELETE CASCADE;

-- fk constraint event_failures event_failures_event_id_fkey

ALTER TABLE ONLY event_failures
    ADD CONSTRAINT event_failures_event_id_fkey FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE;

-- fk constraint evidence_audits evidence_audits_artifact_hash_fkey

ALTER TABLE ONLY evidence_audits
    ADD CONSTRAINT evidence_audits_artifact_hash_fkey FOREIGN KEY (artifact_hash) REFERENCES artifacts(artifact_hash) ON DELETE CASCADE;

-- fk constraint evidence_audits evidence_audits_campaign_id_candidate_id_fkey

ALTER TABLE ONLY evidence_audits
    ADD CONSTRAINT evidence_audits_campaign_id_candidate_id_fkey FOREIGN KEY (campaign_id, candidate_id) REFERENCES campaign_candidates(campaign_id, candidate_id) ON DELETE CASCADE;

-- fk constraint four_rung_phenotypes four_rung_phenotypes_campaign_id_candidate_id_fkey

ALTER TABLE ONLY four_rung_phenotypes
    ADD CONSTRAINT four_rung_phenotypes_campaign_id_candidate_id_fkey FOREIGN KEY (campaign_id, candidate_id) REFERENCES campaign_candidates(campaign_id, candidate_id) ON DELETE CASCADE;

-- fk constraint jobs jobs_campaign_id_candidate_id_fkey

ALTER TABLE ONLY jobs
    ADD CONSTRAINT jobs_campaign_id_candidate_id_fkey FOREIGN KEY (campaign_id, candidate_id) REFERENCES campaign_candidates(campaign_id, candidate_id) ON DELETE CASCADE;

-- fk constraint locality_audit_results locality_audit_results_campaign_id_candidate_id_fkey

ALTER TABLE ONLY locality_audit_results
    ADD CONSTRAINT locality_audit_results_campaign_id_candidate_id_fkey FOREIGN KEY (campaign_id, candidate_id) REFERENCES campaign_candidates(campaign_id, candidate_id) ON DELETE CASCADE;

-- fk constraint measurements measurements_campaign_id_candidate_id_fkey

ALTER TABLE ONLY measurements
    ADD CONSTRAINT measurements_campaign_id_candidate_id_fkey FOREIGN KEY (campaign_id, candidate_id) REFERENCES campaign_candidates(campaign_id, candidate_id) ON DELETE CASCADE;

-- fk constraint measurements measurements_curves_artifact_fkey

ALTER TABLE ONLY measurements
    ADD CONSTRAINT measurements_curves_artifact_fkey FOREIGN KEY (curves_artifact) REFERENCES artifacts(artifact_hash) ON DELETE SET NULL;

-- fk constraint measurements measurements_input_artifact_fkey

ALTER TABLE ONLY measurements
    ADD CONSTRAINT measurements_input_artifact_fkey FOREIGN KEY (input_artifact) REFERENCES artifacts(artifact_hash) ON DELETE RESTRICT;

-- fk constraint proposal_assessments proposal_assessments_campaign_id_candidate_id_fkey

ALTER TABLE ONLY proposal_assessments
    ADD CONSTRAINT proposal_assessments_campaign_id_candidate_id_fkey FOREIGN KEY (campaign_id, candidate_id) REFERENCES campaign_candidates(campaign_id, candidate_id) ON DELETE CASCADE;

-- fk constraint proposal_draws proposal_draws_campaign_id_fkey

ALTER TABLE ONLY proposal_draws
    ADD CONSTRAINT proposal_draws_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint proposal_exposures proposal_exposures_campaign_id_fkey

ALTER TABLE ONLY proposal_exposures
    ADD CONSTRAINT proposal_exposures_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint proposal_policy_epochs proposal_policy_epochs_campaign_id_fkey

ALTER TABLE ONLY proposal_policy_epochs
    ADD CONSTRAINT proposal_policy_epochs_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint resource_calibration_runs resource_calibration_runs_campaign_id_fkey

ALTER TABLE ONLY resource_calibration_runs
    ADD CONSTRAINT resource_calibration_runs_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint resource_governor_events resource_governor_events_calibration_id_fkey

ALTER TABLE ONLY resource_governor_events
    ADD CONSTRAINT resource_governor_events_calibration_id_fkey FOREIGN KEY (calibration_id) REFERENCES resource_calibration_runs(calibration_id) ON DELETE SET NULL;

-- fk constraint resource_governor_events resource_governor_events_campaign_id_fkey

ALTER TABLE ONLY resource_governor_events
    ADD CONSTRAINT resource_governor_events_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint resource_telemetry resource_telemetry_campaign_id_fkey

ALTER TABLE ONLY resource_telemetry
    ADD CONSTRAINT resource_telemetry_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE;

-- fk constraint rung_diagnostics rung_diagnostics_campaign_id_candidate_id_fkey

ALTER TABLE ONLY rung_diagnostics
    ADD CONSTRAINT rung_diagnostics_campaign_id_candidate_id_fkey FOREIGN KEY (campaign_id, candidate_id) REFERENCES campaign_candidates(campaign_id, candidate_id) ON DELETE CASCADE;

-- fk constraint rung_operational_terminals rung_operational_terminals_campaign_id_candidate_id_fkey

ALTER TABLE ONLY rung_operational_terminals
    ADD CONSTRAINT rung_operational_terminals_campaign_id_candidate_id_fkey FOREIGN KEY (campaign_id, candidate_id) REFERENCES campaign_candidates(campaign_id, candidate_id) ON DELETE CASCADE;

-- fk constraint rung_summaries rung_summaries_campaign_id_candidate_id_fkey

ALTER TABLE ONLY rung_summaries
    ADD CONSTRAINT rung_summaries_campaign_id_candidate_id_fkey FOREIGN KEY (campaign_id, candidate_id) REFERENCES campaign_candidates(campaign_id, candidate_id) ON DELETE CASCADE;

-- PostgreSQL database dump complete

-- seed: the read-model watermark singleton (migration 038 seeded it; a fresh
-- database needs the row before the first fact is applied)
INSERT INTO read_model_state(id, watermark, events_applied)
VALUES (1, 0, 0)
ON CONFLICT (id) DO NOTHING;
