"""Fresh prototype baseline; intentionally incompatible with the old migration chain."""

from alembic import op

revision = "20260905_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("The baseline requires PostgreSQL; SQLite tests use model metadata.")
    op.execute("""
CREATE TABLE users (
	id UUID NOT NULL,
	issuer VARCHAR(500) NOT NULL,
	subject VARCHAR(255) NOT NULL,
	email VARCHAR(320),
	display_name VARCHAR(200),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_users_issuer_subject UNIQUE (issuer, subject)
)
""")
    op.execute("""
CREATE INDEX ix_users_email ON users (email)
""")
    op.execute("""
CREATE TABLE local_accounts (
	id UUID NOT NULL,
	username VARCHAR(80) NOT NULL,
	password_digest VARCHAR(300) NOT NULL,
	display_name VARCHAR(200),
	is_admin BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
)
""")
    op.execute("""
CREATE UNIQUE INDEX ix_local_accounts_username ON local_accounts (username)
""")
    op.execute("""
CREATE TABLE platform_agent_versions (
	id UUID NOT NULL,
	agent_kind VARCHAR(32) NOT NULL,
	version INTEGER NOT NULL,
	display_name VARCHAR(200) NOT NULL,
	instructions_text TEXT NOT NULL,
	instructions_digest VARCHAR(64) NOT NULL,
	execution_profile VARCHAR(32) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_platform_agent_versions_kind_version UNIQUE (agent_kind, version),
	CONSTRAINT ck_platform_agent_versions_kind CHECK (agent_kind IN ('RESEARCHER', 'CRITIC')),
	CONSTRAINT ck_platform_agent_versions_execution_profile CHECK (execution_profile IN
('TRUSTED_HOSTED')),
	UNIQUE (instructions_digest)
)
""")
    op.execute("""
CREATE TABLE execution_rate_windows (
	id UUID NOT NULL,
	scope VARCHAR(16) NOT NULL,
	scope_id UUID NOT NULL,
	window_started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	count INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_execution_rate_window UNIQUE (scope, scope_id, window_started_at),
	CONSTRAINT ck_execution_rate_window_scope CHECK (scope IN ('user', 'project', 'public_ip',
'sse_user')),
	CONSTRAINT ck_execution_rate_window_count CHECK (count >= 0)
)
""")
    op.execute("""
CREATE INDEX ix_execution_rate_windows_scope_id ON execution_rate_windows (scope_id)
""")
    op.execute("""
CREATE INDEX ix_execution_rate_windows_window_started_at ON execution_rate_windows
(window_started_at)
""")
    op.execute("""
CREATE TABLE operational_metric_aggregates (
	id UUID NOT NULL,
	metric_name VARCHAR(128) NOT NULL,
	labels_key VARCHAR(256) NOT NULL,
	labels JSON NOT NULL,
	counter_value BIGINT NOT NULL,
	observation_count BIGINT NOT NULL,
	observation_sum FLOAT NOT NULL,
	observation_max FLOAT NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_operational_metric_series UNIQUE (metric_name, labels_key),
	CONSTRAINT ck_operational_metric_name_length CHECK (length(metric_name) <= 128),
	CONSTRAINT ck_operational_metric_labels_length CHECK (length(labels_key) <= 256),
	CONSTRAINT ck_operational_metric_counter_nonnegative CHECK (counter_value >= 0),
	CONSTRAINT ck_operational_metric_count_nonnegative CHECK (observation_count >= 0),
	CONSTRAINT ck_operational_metric_sum_nonnegative CHECK (observation_sum >= 0),
	CONSTRAINT ck_operational_metric_max_nonnegative CHECK (observation_max >= 0)
)
""")
    op.execute("""
CREATE TABLE mutation_receipts (
	id UUID NOT NULL,
	actor_key VARCHAR(200) NOT NULL,
	operation VARCHAR(64) NOT NULL,
	idempotency_key_digest VARCHAR(64) NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	status VARCHAR(16) NOT NULL,
	resource_ids JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_mutation_receipts_key UNIQUE (actor_key, operation, idempotency_key_digest),
	CONSTRAINT ck_mutation_receipts_status CHECK (status IN ('COMMITTED', 'FAILED')),
	CONSTRAINT ck_mutation_receipts_digest_length CHECK (length(idempotency_key_digest) = 64 AND
length(request_digest) = 64)
)
""")
    op.execute("""
CREATE INDEX ix_mutation_receipts_actor_key ON mutation_receipts (actor_key)
""")
    op.execute("""
CREATE TABLE auth_sessions (
	id UUID NOT NULL,
	account_id UUID NOT NULL,
	token_digest VARCHAR(64) NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(account_id) REFERENCES local_accounts (id)
)
""")
    op.execute("""
CREATE INDEX ix_auth_sessions_account_id ON auth_sessions (account_id)
""")
    op.execute("""
CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions (expires_at)
""")
    op.execute("""
CREATE UNIQUE INDEX ix_auth_sessions_token_digest ON auth_sessions (token_digest)
""")
    op.execute("""
CREATE TABLE gateway_profiles (
	id UUID NOT NULL,
	user_id UUID NOT NULL,
	display_name VARCHAR(200) NOT NULL,
	base_url VARCHAR(2048) NOT NULL,
	model_id VARCHAR(500) NOT NULL,
	credential_version INTEGER NOT NULL,
	encrypted_credential BYTEA NOT NULL,
	wrapped_data_key BYTEA NOT NULL,
	encryption_key_version VARCHAR(200) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_gateway_profiles_user_id ON gateway_profiles (user_id)
""")
    op.execute("""
CREATE TABLE projects (
	id UUID NOT NULL,
	name VARCHAR(200) NOT NULL,
	description TEXT,
	visibility VARCHAR(16) NOT NULL,
	created_by_user_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	archived_at TIMESTAMP WITH TIME ZONE,
	deleted_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT ck_projects_private CHECK (visibility = 'PRIVATE'),
	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_projects_created_by_user_id ON projects (created_by_user_id)
""")
    op.execute("""
CREATE TABLE gateway_run_grants (
	id UUID NOT NULL,
	token_digest VARCHAR(64) NOT NULL,
	user_id UUID NOT NULL,
	profile_id UUID NOT NULL,
	run_id UUID NOT NULL,
	model_id VARCHAR(500) NOT NULL,
	credential_version INTEGER NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	used_at TIMESTAMP WITH TIME ZONE,
	revoked BOOLEAN NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(profile_id) REFERENCES gateway_profiles (id)
)
""")
    op.execute("""
CREATE UNIQUE INDEX ix_gateway_run_grants_token_digest ON gateway_run_grants (token_digest)
""")
    op.execute("""
CREATE INDEX ix_gateway_run_grants_profile_id ON gateway_run_grants (profile_id)
""")
    op.execute("""
CREATE INDEX ix_gateway_run_grants_expires_at ON gateway_run_grants (expires_at)
""")
    op.execute("""
CREATE INDEX ix_gateway_run_grants_run_id ON gateway_run_grants (run_id)
""")
    op.execute("""
CREATE INDEX ix_gateway_run_grants_user_id ON gateway_run_grants (user_id)
""")
    op.execute("""
CREATE TABLE memberships (
	id UUID NOT NULL,
	project_id UUID NOT NULL,
	user_id UUID NOT NULL,
	role VARCHAR(16) NOT NULL,
	invited_by_user_id UUID,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_memberships_project_user UNIQUE (project_id, user_id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(invited_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_memberships_project_id ON memberships (project_id)
""")
    op.execute("""
CREATE INDEX ix_memberships_user_id ON memberships (user_id)
""")
    op.execute("""
CREATE TABLE invitations (
	id UUID NOT NULL,
	project_id UUID NOT NULL,
	email VARCHAR(320) NOT NULL,
	role VARCHAR(16) NOT NULL,
	token_digest VARCHAR(64) NOT NULL,
	invited_by_user_id UUID NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	status VARCHAR(16) NOT NULL,
	accepted_by_user_id UUID,
	accepted_at TIMESTAMP WITH TIME ZONE,
	revoked_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(invited_by_user_id) REFERENCES users (id),
	FOREIGN KEY(accepted_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_invitations_email ON invitations (email)
""")
    op.execute("""
CREATE INDEX ix_invitations_invited_by_user_id ON invitations (invited_by_user_id)
""")
    op.execute("""
CREATE UNIQUE INDEX ix_invitations_token_digest ON invitations (token_digest)
""")
    op.execute("""
CREATE INDEX ix_invitations_project_id ON invitations (project_id)
""")
    op.execute("""
CREATE TABLE research_scopes (
	id UUID NOT NULL,
	scope_kind VARCHAR(16) NOT NULL,
	project_id UUID,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_research_scopes_project UNIQUE (project_id),
	CONSTRAINT uq_research_scopes_id_project UNIQUE (id, project_id),
	CONSTRAINT ck_research_scopes_kind_project CHECK ((scope_kind = 'COMMONS' AND project_id IS
NULL) OR (scope_kind = 'WORKSPACE' AND project_id IS NOT NULL)),
	FOREIGN KEY(project_id) REFERENCES projects (id)
)
""")
    op.execute("""
CREATE UNIQUE INDEX uq_research_scopes_commons ON research_scopes (scope_kind) WHERE
scope_kind = 'COMMONS'
""")
    op.execute("""
CREATE INDEX ix_research_scopes_project_id ON research_scopes (project_id)
""")
    op.execute("""
CREATE TABLE agent_sessions (
	id UUID NOT NULL,
	project_id UUID NOT NULL,
	agent_version_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	title VARCHAR(300),
	status VARCHAR(16) NOT NULL,
	next_message_sequence INTEGER NOT NULL,
	next_run_sequence INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	archived_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_agent_sessions_id_project UNIQUE (id, project_id),
	CONSTRAINT ck_agent_sessions_message_sequence CHECK (next_message_sequence >= 0),
	CONSTRAINT ck_agent_sessions_run_sequence CHECK (next_run_sequence >= 0),
	CONSTRAINT ck_agent_sessions_status CHECK (status IN ('ACTIVE', 'ARCHIVED')),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(agent_version_id) REFERENCES platform_agent_versions (id),
	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_agent_sessions_agent_version_id ON agent_sessions (agent_version_id)
""")
    op.execute("""
CREATE INDEX ix_agent_sessions_created_by_user_id ON agent_sessions (created_by_user_id)
""")
    op.execute("""
CREATE INDEX ix_agent_sessions_project_id ON agent_sessions (project_id)
""")
    op.execute("""
CREATE TABLE agent_messages (
	id UUID NOT NULL,
	session_id UUID NOT NULL,
	sequence INTEGER NOT NULL,
	role VARCHAR(16) NOT NULL,
	author_user_id UUID,
	content_md TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_agent_messages_id_session UNIQUE (id, session_id),
	CONSTRAINT uq_agent_messages_session_sequence UNIQUE (session_id, sequence),
	CONSTRAINT ck_agent_messages_sequence CHECK (sequence > 0),
	CONSTRAINT ck_agent_messages_role CHECK (role IN ('USER', 'AGENT', 'SYSTEM')),
	FOREIGN KEY(session_id) REFERENCES agent_sessions (id),
	FOREIGN KEY(author_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_agent_messages_session_id ON agent_messages (session_id)
""")
    op.execute("""
CREATE TABLE runtime_session_bindings (
	id UUID NOT NULL,
	session_id UUID NOT NULL,
	adapter_name VARCHAR(100) NOT NULL,
	opaque_runtime_ref VARCHAR(500),
	status VARCHAR(16) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	ended_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_runtime_session_bindings_id_session UNIQUE (id, session_id),
	CONSTRAINT ck_runtime_session_bindings_status CHECK (status IN ('ACTIVE', 'SUPERSEDED',
'ARCHIVED')),
	FOREIGN KEY(session_id) REFERENCES agent_sessions (id)
)
""")
    op.execute("""
CREATE INDEX ix_runtime_session_bindings_session_id ON runtime_session_bindings (session_id)
""")
    op.execute("""
CREATE UNIQUE INDEX uq_runtime_session_bindings_active_session ON runtime_session_bindings
(session_id) WHERE status = 'ACTIVE'
""")
    op.execute("""
CREATE TABLE outbox_events (
	id UUID NOT NULL,
	event_type VARCHAR(100) NOT NULL,
	aggregate_type VARCHAR(64) NOT NULL,
	aggregate_id UUID NOT NULL,
	ownership_scope_id UUID,
	payload JSON NOT NULL,
	payload_digest VARCHAR(64) NOT NULL,
	status VARCHAR(16) NOT NULL,
	attempts INTEGER NOT NULL,
	available_at TIMESTAMP WITH TIME ZONE NOT NULL,
	claimed_by VARCHAR(100),
	claimed_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_outbox_events_status CHECK (status IN ('PENDING', 'CLAIMED', 'DELIVERED',
'FAILED')),
	CONSTRAINT ck_outbox_events_attempts CHECK (attempts >= 0),
	CONSTRAINT ck_outbox_events_digest_length CHECK (length(payload_digest) = 64),
	FOREIGN KEY(ownership_scope_id) REFERENCES research_scopes (id)
)
""")
    op.execute("""
CREATE INDEX ix_outbox_events_claim ON outbox_events (available_at, created_at, id)
""")
    op.execute("""
CREATE INDEX ix_outbox_events_ownership_scope_id ON outbox_events (ownership_scope_id)
""")
    op.execute("""
CREATE INDEX ix_outbox_events_event_type ON outbox_events (event_type)
""")
    op.execute("""
CREATE INDEX ix_outbox_events_aggregate_id ON outbox_events (aggregate_id)
""")
    op.execute("""
CREATE TABLE agent_runs (
	id UUID NOT NULL,
	session_id UUID NOT NULL,
	project_id UUID NOT NULL,
	agent_version_id UUID NOT NULL,
	requested_by_user_id UUID NOT NULL,
	request_message_id UUID,
	client_request_id UUID NOT NULL,
	parent_run_id UUID,
	gateway_profile_id UUID NOT NULL,
	gateway_credential_version INTEGER NOT NULL,
	gateway_model_id VARCHAR(500) NOT NULL,
	queue_sequence INTEGER NOT NULL,
	input_message_sequence INTEGER NOT NULL,
	requested_context_revision_ids JSON NOT NULL,
	status VARCHAR(16) NOT NULL,
	attempt INTEGER NOT NULL,
	lease_generation INTEGER NOT NULL,
	lease_owner VARCHAR(200),
	lease_expires_at TIMESTAMP WITH TIME ZONE,
	cancel_requested_at TIMESTAMP WITH TIME ZONE,
	deadline_at TIMESTAMP WITH TIME ZONE,
	started_at TIMESTAMP WITH TIME ZONE,
	finished_at TIMESTAMP WITH TIME ZONE,
	failure_code VARCHAR(64),
	next_event_cursor INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_agent_runs_id_session UNIQUE (id, session_id),
	CONSTRAINT uq_agent_runs_scope UNIQUE (id, project_id, requested_by_user_id,
agent_version_id),
	CONSTRAINT uq_agent_runs_full_scope UNIQUE (id, session_id, project_id,
requested_by_user_id, agent_version_id),
	CONSTRAINT uq_agent_runs_request_message UNIQUE (request_message_id),
	CONSTRAINT uq_agent_runs_client_request UNIQUE (session_id, client_request_id),
	CONSTRAINT uq_agent_runs_session_queue UNIQUE (session_id, queue_sequence),
	CONSTRAINT fk_agent_runs_session_project FOREIGN KEY(session_id, project_id) REFERENCES
agent_sessions (id, project_id),
	CONSTRAINT fk_agent_runs_request_message_session FOREIGN KEY(request_message_id, session_id)
REFERENCES agent_messages (id, session_id),
	CONSTRAINT ck_agent_runs_queue_sequence CHECK (queue_sequence > 0),
	CONSTRAINT ck_agent_runs_input_message_sequence CHECK (input_message_sequence > 0),
	CONSTRAINT ck_agent_runs_attempt CHECK (attempt >= 0),
	CONSTRAINT ck_agent_runs_lease_generation CHECK (lease_generation >= 0),
	CONSTRAINT ck_agent_runs_event_cursor CHECK (next_event_cursor >= 0),
	CONSTRAINT ck_agent_runs_status CHECK (status IN ('QUEUED', 'CLAIMED', 'RUNNING',
'CANCELLING', 'COMPLETED', 'CANCELLED', 'FAILED', 'TIMED_OUT')),
	FOREIGN KEY(agent_version_id) REFERENCES platform_agent_versions (id),
	FOREIGN KEY(requested_by_user_id) REFERENCES users (id),
	FOREIGN KEY(parent_run_id) REFERENCES agent_runs (id),
	FOREIGN KEY(gateway_profile_id) REFERENCES gateway_profiles (id)
)
""")
    op.execute("""
CREATE INDEX ix_agent_runs_client_request_id ON agent_runs (client_request_id)
""")
    op.execute("""
CREATE INDEX ix_agent_runs_gateway_profile_id ON agent_runs (gateway_profile_id)
""")
    op.execute("""
CREATE INDEX ix_agent_runs_requested_by_user_id ON agent_runs (requested_by_user_id)
""")
    op.execute("""
CREATE INDEX ix_agent_runs_project_id ON agent_runs (project_id)
""")
    op.execute("""
CREATE INDEX ix_agent_runs_agent_version_id ON agent_runs (agent_version_id)
""")
    op.execute("""
CREATE INDEX ix_agent_runs_session_id ON agent_runs (session_id)
""")
    op.execute("""
CREATE TABLE outbox_consumer_receipts (
	id UUID NOT NULL,
	event_id UUID NOT NULL,
	consumer_name VARCHAR(100) NOT NULL,
	outcome VARCHAR(32) NOT NULL,
	attempts INTEGER NOT NULL,
	last_error VARCHAR(500),
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_outbox_consumer_receipt UNIQUE (event_id, consumer_name),
	CONSTRAINT ck_outbox_consumer_receipts_attempts CHECK (attempts >= 0),
	FOREIGN KEY(event_id) REFERENCES outbox_events (id)
)
""")
    op.execute("""
CREATE INDEX ix_outbox_consumer_receipts_event_id ON outbox_consumer_receipts (event_id)
""")
    op.execute("""
CREATE TABLE agent_run_events (
	id UUID NOT NULL,
	run_id UUID NOT NULL,
	cursor INTEGER NOT NULL,
	idempotency_key VARCHAR(200) NOT NULL,
	kind VARCHAR(32) NOT NULL,
	payload JSON NOT NULL,
	occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_agent_run_events_run_cursor UNIQUE (run_id, cursor),
	CONSTRAINT uq_agent_run_events_run_key UNIQUE (run_id, idempotency_key),
	CONSTRAINT ck_agent_run_events_cursor CHECK (cursor > 0),
	CONSTRAINT ck_agent_run_events_kind CHECK (kind IN ('RUN_STARTED', 'ASSISTANT_DELTA',
'ASSISTANT_MESSAGE_COMPLETED', 'USAGE_REPORTED', 'CANCEL_REQUESTED', 'RUN_COMPLETED',
'RUN_CANCELLED', 'RUN_FAILED', 'RUN_TIMED_OUT', 'RUNNER_LOST', 'TOOL_REQUESTED',
'TOOL_RESULT')),
	FOREIGN KEY(run_id) REFERENCES agent_runs (id)
)
""")
    op.execute("""
CREATE INDEX ix_agent_run_events_run_id ON agent_run_events (run_id)
""")
    op.execute("""
CREATE TABLE operator_diagnostic_accesses (
	id UUID NOT NULL,
	run_id UUID NOT NULL,
	operator_subject_digest VARCHAR(64) NOT NULL,
	request_id UUID NOT NULL,
	accessed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_operator_diagnostic_access_subject_digest CHECK
(length(operator_subject_digest) = 64),
	FOREIGN KEY(run_id) REFERENCES agent_runs (id)
)
""")
    op.execute("""
CREATE INDEX ix_operator_diagnostic_accesses_run_id ON operator_diagnostic_accesses (run_id)
""")
    op.execute("""
CREATE INDEX ix_operator_diagnostic_accesses_request_id ON operator_diagnostic_accesses
(request_id)
""")
    op.execute("""
CREATE TABLE runtime_run_bindings (
	id UUID NOT NULL,
	run_id UUID NOT NULL,
	session_id UUID NOT NULL,
	session_binding_id UUID NOT NULL,
	adapter_name VARCHAR(100) NOT NULL,
	opaque_runtime_ref VARCHAR(500),
	status VARCHAR(16) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	ended_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	CONSTRAINT uq_runtime_run_bindings_run UNIQUE (run_id),
	CONSTRAINT fk_runtime_run_bindings_run_session FOREIGN KEY(run_id, session_id) REFERENCES
agent_runs (id, session_id),
	CONSTRAINT fk_runtime_run_bindings_session_binding FOREIGN KEY(session_binding_id,
session_id) REFERENCES runtime_session_bindings (id, session_id),
	CONSTRAINT ck_runtime_run_bindings_status CHECK (status IN ('PENDING', 'ACTIVE', 'FINISHED',
'LOST'))
)
""")
    op.execute("""
CREATE INDEX ix_runtime_run_bindings_session_binding_id ON runtime_run_bindings
(session_binding_id)
""")
    op.execute("""
CREATE INDEX ix_runtime_run_bindings_run_id ON runtime_run_bindings (run_id)
""")
    op.execute("""
CREATE INDEX ix_runtime_run_bindings_session_id ON runtime_run_bindings (session_id)
""")
    op.execute("""
CREATE TABLE context_manifests (
	id UUID NOT NULL,
	run_id UUID NOT NULL,
	project_id UUID NOT NULL,
	requested_by_user_id UUID NOT NULL,
	agent_version_id UUID NOT NULL,
	revision_ids JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_context_manifests_run UNIQUE (run_id),
	CONSTRAINT uq_context_manifests_scope UNIQUE (id, run_id, project_id, requested_by_user_id,
agent_version_id),
	CONSTRAINT fk_context_manifests_run_scope FOREIGN KEY(run_id, project_id,
requested_by_user_id, agent_version_id) REFERENCES agent_runs (id, project_id,
requested_by_user_id, agent_version_id),
	FOREIGN KEY(run_id) REFERENCES agent_runs (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(requested_by_user_id) REFERENCES users (id),
	FOREIGN KEY(agent_version_id) REFERENCES platform_agent_versions (id)
)
""")
    op.execute("""
CREATE INDEX ix_context_manifests_run_id ON context_manifests (run_id)
""")
    op.execute("""
CREATE INDEX ix_context_manifests_requested_by_user_id ON context_manifests
(requested_by_user_id)
""")
    op.execute("""
CREATE INDEX ix_context_manifests_project_id ON context_manifests (project_id)
""")
    op.execute("""
CREATE TABLE agent_run_usage (
	id UUID NOT NULL,
	run_id UUID NOT NULL,
	event_cursor INTEGER,
	source VARCHAR(32) NOT NULL,
	input_tokens INTEGER,
	output_tokens INTEGER,
	total_tokens INTEGER,
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_agent_run_usage_event UNIQUE (run_id, event_cursor),
	CONSTRAINT fk_agent_run_usage_event FOREIGN KEY(run_id, event_cursor) REFERENCES
agent_run_events (run_id, cursor),
	CONSTRAINT ck_agent_run_usage_input CHECK (input_tokens IS NULL OR input_tokens >= 0),
	CONSTRAINT ck_agent_run_usage_output CHECK (output_tokens IS NULL OR output_tokens >= 0),
	CONSTRAINT ck_agent_run_usage_total CHECK (total_tokens IS NULL OR total_tokens >= 0),
	CONSTRAINT ck_agent_run_usage_source CHECK (source IN ('PROVIDER_REPORTED', 'ESTIMATED',
'UNKNOWN')),
	FOREIGN KEY(run_id) REFERENCES agent_runs (id)
)
""")
    op.execute("""
CREATE INDEX ix_agent_run_usage_run_id ON agent_run_usage (run_id)
""")
    op.execute("""
CREATE TABLE run_tool_capabilities (
	id UUID NOT NULL,
	token_digest VARCHAR(64) NOT NULL,
	run_id UUID NOT NULL,
	session_id UUID NOT NULL,
	project_id UUID NOT NULL,
	user_id UUID NOT NULL,
	agent_version_id UUID NOT NULL,
	context_manifest_id UUID NOT NULL,
	allowed_tools JSON NOT NULL,
	lease_generation INTEGER NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked BOOLEAN NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_run_tool_capabilities_lease_generation CHECK (lease_generation >= 0),
	CONSTRAINT fk_run_tool_capabilities_manifest_scope FOREIGN KEY(context_manifest_id, run_id,
project_id, user_id, agent_version_id) REFERENCES context_manifests (id, run_id, project_id,
requested_by_user_id, agent_version_id),
	FOREIGN KEY(run_id) REFERENCES agent_runs (id),
	FOREIGN KEY(session_id) REFERENCES agent_sessions (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(agent_version_id) REFERENCES platform_agent_versions (id),
	FOREIGN KEY(context_manifest_id) REFERENCES context_manifests (id)
)
""")
    op.execute("""
CREATE INDEX ix_run_tool_capabilities_session_id ON run_tool_capabilities (session_id)
""")
    op.execute("""
CREATE INDEX ix_run_tool_capabilities_project_id ON run_tool_capabilities (project_id)
""")
    op.execute("""
CREATE INDEX ix_run_tool_capabilities_run_id ON run_tool_capabilities (run_id)
""")
    op.execute("""
CREATE UNIQUE INDEX ix_run_tool_capabilities_token_digest ON run_tool_capabilities
(token_digest)
""")
    op.execute("""
CREATE INDEX ix_run_tool_capabilities_user_id ON run_tool_capabilities (user_id)
""")
    op.execute("""
CREATE INDEX ix_run_tool_capabilities_expires_at ON run_tool_capabilities (expires_at)
""")
    op.execute("""
CREATE TABLE proposals (
	id UUID NOT NULL,
	project_id UUID NOT NULL,
	session_id UUID NOT NULL,
	run_id UUID NOT NULL,
	agent_version_id UUID NOT NULL,
	context_manifest_id UUID NOT NULL,
	requested_by_user_id UUID NOT NULL,
	idempotency_key VARCHAR(200) NOT NULL,
	summary TEXT NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_proposals_run_key UNIQUE (run_id, idempotency_key),
	CONSTRAINT uq_proposals_id_project UNIQUE (id, project_id),
	CONSTRAINT fk_proposals_manifest_scope FOREIGN KEY(context_manifest_id, run_id, project_id,
requested_by_user_id, agent_version_id) REFERENCES context_manifests (id, run_id, project_id,
requested_by_user_id, agent_version_id),
	CONSTRAINT fk_proposals_session_project FOREIGN KEY(session_id, project_id) REFERENCES
agent_sessions (id, project_id),
	CONSTRAINT fk_proposals_run_session_scope FOREIGN KEY(run_id, session_id, project_id,
requested_by_user_id, agent_version_id) REFERENCES agent_runs (id, session_id, project_id,
requested_by_user_id, agent_version_id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(session_id) REFERENCES agent_sessions (id),
	FOREIGN KEY(run_id) REFERENCES agent_runs (id),
	FOREIGN KEY(agent_version_id) REFERENCES platform_agent_versions (id),
	FOREIGN KEY(context_manifest_id) REFERENCES context_manifests (id),
	FOREIGN KEY(requested_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_proposals_session_id ON proposals (session_id)
""")
    op.execute("""
CREATE INDEX ix_proposals_project_id ON proposals (project_id)
""")
    op.execute("""
CREATE INDEX ix_proposals_run_id ON proposals (run_id)
""")
    op.execute("""
CREATE INDEX ix_proposals_requested_by_user_id ON proposals (requested_by_user_id)
""")
    op.execute("""
CREATE TABLE proposal_changes (
	id UUID NOT NULL,
	proposal_id UUID NOT NULL,
	project_id UUID NOT NULL,
	ordinal INTEGER NOT NULL,
	change_type VARCHAR(32) NOT NULL,
	payload JSON NOT NULL,
	status VARCHAR(16) NOT NULL,
	decided_by_user_id UUID,
	decided_at TIMESTAMP WITH TIME ZONE,
	applied_entity_id UUID,
	rejection_reason TEXT,
	source_event_cursors JSON NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_proposal_changes_ordinal UNIQUE (proposal_id, ordinal),
	CONSTRAINT ck_proposal_changes_ordinal CHECK (ordinal > 0),
	CONSTRAINT ck_proposal_changes_type CHECK (change_type IN ('CREATE_OBJECT',
'CREATE_REVISION', 'CREATE_RELATION', 'CREATE_COMMENT')),
	CONSTRAINT ck_proposal_changes_status CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED')),
	CONSTRAINT ck_proposal_changes_decision CHECK ((status = 'PENDING' AND decided_by_user_id IS
NULL AND decided_at IS NULL AND applied_entity_id IS NULL) OR (status = 'REJECTED' AND
decided_by_user_id IS NOT NULL AND decided_at IS NOT NULL AND applied_entity_id IS NULL) OR
(status = 'ACCEPTED' AND decided_by_user_id IS NOT NULL AND decided_at IS NOT NULL AND
applied_entity_id IS NOT NULL)),
	CONSTRAINT uq_proposal_changes_id_project UNIQUE (id, project_id),
	CONSTRAINT fk_proposal_changes_proposal_project FOREIGN KEY(proposal_id, project_id)
REFERENCES proposals (id, project_id),
	FOREIGN KEY(proposal_id) REFERENCES proposals (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(decided_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_proposal_changes_project_id ON proposal_changes (project_id)
""")
    op.execute("""
CREATE INDEX ix_proposal_changes_proposal_id ON proposal_changes (proposal_id)
""")
    op.execute("""
CREATE TABLE proposal_decision_batches (
	id UUID NOT NULL,
	proposal_id UUID NOT NULL,
	project_id UUID NOT NULL,
	idempotency_key_digest VARCHAR(64) NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	decided_by_user_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_proposal_decision_batches_key UNIQUE (proposal_id, idempotency_key_digest),
	CONSTRAINT ck_proposal_decision_batches_digest_length CHECK (length(idempotency_key_digest)
= 64 AND length(request_digest) = 64),
	CONSTRAINT fk_proposal_decision_batches_proposal_project FOREIGN KEY(proposal_id,
project_id) REFERENCES proposals (id, project_id),
	FOREIGN KEY(proposal_id) REFERENCES proposals (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(decided_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_proposal_decision_batches_proposal_id ON proposal_decision_batches
(proposal_id)
""")
    op.execute("""
CREATE INDEX ix_proposal_decision_batches_decided_by_user_id ON proposal_decision_batches
(decided_by_user_id)
""")
    op.execute("""
CREATE INDEX ix_proposal_decision_batches_project_id ON proposal_decision_batches (project_id)
""")
    op.execute("""
CREATE TABLE proposal_change_decisions (
	id UUID NOT NULL,
	proposal_change_id UUID NOT NULL,
	project_id UUID NOT NULL,
	action VARCHAR(16) NOT NULL,
	idempotency_key_digest VARCHAR(64) NOT NULL,
	request_digest VARCHAR(64) NOT NULL,
	decided_by_user_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_proposal_change_decisions_change UNIQUE (proposal_change_id),
	CONSTRAINT uq_proposal_change_decisions_change_key UNIQUE (proposal_change_id,
idempotency_key_digest),
	CONSTRAINT ck_proposal_change_decisions_action CHECK (action IN ('ACCEPT', 'REJECT')),
	CONSTRAINT ck_proposal_change_decisions_digest_length CHECK (length(idempotency_key_digest)
= 64 AND length(request_digest) = 64),
	CONSTRAINT fk_proposal_change_decisions_change_project FOREIGN KEY(proposal_change_id,
project_id) REFERENCES proposal_changes (id, project_id),
	FOREIGN KEY(proposal_change_id) REFERENCES proposal_changes (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(decided_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_proposal_change_decisions_decided_by_user_id ON proposal_change_decisions
(decided_by_user_id)
""")
    op.execute("""
CREATE INDEX ix_proposal_change_decisions_project_id ON proposal_change_decisions (project_id)
""")
    op.execute("""
CREATE INDEX ix_proposal_change_decisions_proposal_change_id ON proposal_change_decisions
(proposal_change_id)
""")
    op.execute("""
CREATE TABLE contribution_envelopes (
	id UUID NOT NULL,
	actor_kind VARCHAR(16) NOT NULL,
	human_user_id UUID,
	sponsor_user_id UUID,
	agent_version_id UUID,
	run_id UUID,
	session_id UUID,
	context_manifest_id UUID,
	ownership_scope_id UUID,
	project_id UUID,
	operation VARCHAR(64) NOT NULL,
	proposal_change_id UUID,
	decided_by_user_id UUID,
	source_event_cursors JSON NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_contribution_run_binding FOREIGN KEY(run_id, session_id, project_id,
sponsor_user_id, agent_version_id) REFERENCES agent_runs (id, session_id, project_id,
requested_by_user_id, agent_version_id),
	CONSTRAINT fk_contribution_manifest_binding FOREIGN KEY(context_manifest_id, run_id,
project_id, sponsor_user_id, agent_version_id) REFERENCES context_manifests (id, run_id,
project_id, requested_by_user_id, agent_version_id),
	CONSTRAINT ck_contribution_review CHECK ((proposal_change_id IS NULL AND decided_by_user_id
IS NULL) OR (actor_kind = 'AGENT' AND proposal_change_id IS NOT NULL AND decided_by_user_id
IS NOT NULL)),
	CONSTRAINT ck_contribution_envelopes_actor_kind CHECK (actor_kind IN ('HUMAN', 'AGENT')),
	CONSTRAINT ck_contribution_envelopes_actor_scope CHECK (((actor_kind = 'HUMAN' AND
human_user_id IS NOT NULL AND sponsor_user_id IS NULL AND agent_version_id IS NULL AND run_id
IS NULL AND session_id IS NULL AND context_manifest_id IS NULL) OR (actor_kind = 'AGENT' AND
human_user_id IS NULL AND sponsor_user_id IS NOT NULL AND agent_version_id IS NOT NULL AND
run_id IS NOT NULL AND session_id IS NOT NULL AND context_manifest_id IS NOT NULL AND
project_id IS NOT NULL))),
	FOREIGN KEY(human_user_id) REFERENCES users (id),
	FOREIGN KEY(sponsor_user_id) REFERENCES users (id),
	FOREIGN KEY(agent_version_id) REFERENCES platform_agent_versions (id),
	FOREIGN KEY(run_id) REFERENCES agent_runs (id),
	FOREIGN KEY(session_id) REFERENCES agent_sessions (id),
	FOREIGN KEY(context_manifest_id) REFERENCES context_manifests (id),
	FOREIGN KEY(ownership_scope_id) REFERENCES research_scopes (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(proposal_change_id) REFERENCES proposal_changes (id),
	FOREIGN KEY(decided_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_contribution_envelopes_ownership_scope_id ON contribution_envelopes
(ownership_scope_id)
""")
    op.execute("""
CREATE TABLE research_objects (
	id UUID NOT NULL,
	ownership_scope_id UUID NOT NULL,
	entity_class VARCHAR(16) NOT NULL,
	kind VARCHAR(32) NOT NULL,
	current_revision_id UUID,
	contribution_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	provenance_kind VARCHAR(32) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_research_objects_kind CHECK (kind IN ('PROBLEM', 'DEFINITION', 'CLAIM',
'PROOF', 'ATTEMPT', 'COUNTEREXAMPLE')),
	CONSTRAINT ck_research_objects_provenance_kind CHECK (provenance_kind IN ('HUMAN_DIRECT',
'AGENT_PROPOSAL', 'AGENT_DIRECT')),
	CONSTRAINT uq_research_objects_id_scope UNIQUE (id, ownership_scope_id),
	FOREIGN KEY(ownership_scope_id) REFERENCES research_scopes (id),
	FOREIGN KEY(contribution_id) REFERENCES contribution_envelopes (id),
	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_research_objects_created_by_user_id ON research_objects (created_by_user_id)
""")
    op.execute("""
CREATE INDEX ix_research_objects_contribution_id ON research_objects (contribution_id)
""")
    op.execute("""
CREATE INDEX ix_research_objects_current_revision_id ON research_objects (current_revision_id)
""")
    op.execute("""
CREATE INDEX ix_research_objects_ownership_scope_id ON research_objects (ownership_scope_id)
""")
    op.execute("""
CREATE TABLE object_revisions (
	id UUID NOT NULL,
	ownership_scope_id UUID NOT NULL,
	object_id UUID NOT NULL,
	schema_version INTEGER NOT NULL,
	number INTEGER NOT NULL,
	title VARCHAR(500) NOT NULL,
	content_md TEXT NOT NULL,
	rationale TEXT,
	base_revision_id UUID,
	contribution_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	provenance_kind VARCHAR(32) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_revision_object_scope FOREIGN KEY(object_id, ownership_scope_id) REFERENCES
research_objects (id, ownership_scope_id),
	CONSTRAINT uq_object_revisions_id_scope UNIQUE (id, ownership_scope_id),
	CONSTRAINT ck_object_revisions_provenance_kind CHECK (provenance_kind IN ('HUMAN_DIRECT',
'AGENT_PROPOSAL', 'AGENT_DIRECT')),
	CONSTRAINT ck_revision_versions CHECK (number > 0 AND schema_version > 0),
	CONSTRAINT uq_object_revisions_number UNIQUE (object_id, number),
	CONSTRAINT uq_object_revisions_id_object UNIQUE (id, object_id),
	CONSTRAINT fk_object_revisions_object_project FOREIGN KEY(object_id) REFERENCES
research_objects (id),
	CONSTRAINT fk_object_revisions_base_object_project FOREIGN KEY(base_revision_id, object_id)
REFERENCES object_revisions (id, object_id),
	FOREIGN KEY(ownership_scope_id) REFERENCES research_scopes (id),
	FOREIGN KEY(contribution_id) REFERENCES contribution_envelopes (id),
	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_object_revisions_ownership_scope_id ON object_revisions (ownership_scope_id)
""")
    op.execute("""
CREATE INDEX ix_object_revisions_created_by_user_id ON object_revisions (created_by_user_id)
""")
    op.execute("""
CREATE INDEX ix_object_revisions_object_id ON object_revisions (object_id)
""")
    op.execute("""
CREATE INDEX ix_object_revisions_contribution_id ON object_revisions (contribution_id)
""")
    op.execute("""
CREATE TABLE relation_assertions (
	id UUID NOT NULL,
	ownership_scope_id UUID NOT NULL,
	source_revision_id UUID NOT NULL,
	target_revision_id UUID NOT NULL,
	relation_type VARCHAR(32) NOT NULL,
	rationale TEXT NOT NULL,
	contribution_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	provenance_kind VARCHAR(32) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_relation_source_scope FOREIGN KEY(source_revision_id, ownership_scope_id)
REFERENCES object_revisions (id, ownership_scope_id),
	CONSTRAINT ck_relation_assertions_relation_type CHECK (relation_type IN ('DEPENDS_ON',
'PROVES', 'ATTEMPTS', 'REFUTES', 'USES')),
	CONSTRAINT ck_relation_assertions_provenance_kind CHECK (provenance_kind IN ('HUMAN_DIRECT',
'AGENT_PROPOSAL', 'AGENT_DIRECT')),
	CONSTRAINT fk_relation_assertions_source_project FOREIGN KEY(source_revision_id) REFERENCES
object_revisions (id),
	CONSTRAINT fk_relation_assertions_target_project FOREIGN KEY(target_revision_id) REFERENCES
object_revisions (id),
	FOREIGN KEY(ownership_scope_id) REFERENCES research_scopes (id),
	FOREIGN KEY(contribution_id) REFERENCES contribution_envelopes (id),
	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_relation_assertions_contribution_id ON relation_assertions (contribution_id)
""")
    op.execute("""
CREATE INDEX ix_relation_assertions_created_by_user_id ON relation_assertions
(created_by_user_id)
""")
    op.execute("""
CREATE INDEX ix_relation_assertions_target_revision_id ON relation_assertions
(target_revision_id)
""")
    op.execute("""
CREATE INDEX ix_relation_assertions_source_revision_id ON relation_assertions
(source_revision_id)
""")
    op.execute("""
CREATE INDEX ix_relation_assertions_ownership_scope_id ON relation_assertions
(ownership_scope_id)
""")
    op.execute("""
CREATE TABLE research_comments (
	id UUID NOT NULL,
	ownership_scope_id UUID NOT NULL,
	object_id UUID NOT NULL,
	revision_id UUID NOT NULL,
	body_md TEXT NOT NULL,
	contribution_id UUID NOT NULL,
	created_by_user_id UUID NOT NULL,
	provenance_kind VARCHAR(32) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_comment_object_scope FOREIGN KEY(object_id, ownership_scope_id) REFERENCES
research_objects (id, ownership_scope_id),
	CONSTRAINT ck_research_comments_provenance_kind CHECK (provenance_kind IN ('HUMAN_DIRECT',
'AGENT_PROPOSAL', 'AGENT_DIRECT')),
	CONSTRAINT fk_research_comments_revision_object_project FOREIGN KEY(revision_id, object_id)
REFERENCES object_revisions (id, object_id),
	FOREIGN KEY(ownership_scope_id) REFERENCES research_scopes (id),
	FOREIGN KEY(contribution_id) REFERENCES contribution_envelopes (id),
	FOREIGN KEY(created_by_user_id) REFERENCES users (id)
)
""")
    op.execute("""
CREATE INDEX ix_research_comments_revision_id ON research_comments (revision_id)
""")
    op.execute("""
CREATE INDEX ix_research_comments_ownership_scope_id ON research_comments (ownership_scope_id)
""")
    op.execute("""
CREATE INDEX ix_research_comments_contribution_id ON research_comments (contribution_id)
""")
    op.execute("""
CREATE INDEX ix_research_comments_created_by_user_id ON research_comments (created_by_user_id)
""")
    op.execute("""
CREATE INDEX ix_research_comments_object_id ON research_comments (object_id)
""")
    op.execute("""
CREATE TABLE statement_revisions (
	revision_id UUID NOT NULL,
	kind VARCHAR(32) NOT NULL,
	assumptions_md TEXT NOT NULL,
	PRIMARY KEY (revision_id),
	CONSTRAINT ck_statement_kind CHECK (kind IN ('PROBLEM', 'DEFINITION', 'CLAIM')),
	FOREIGN KEY(revision_id) REFERENCES object_revisions (id)
)
""")
    op.execute("""
CREATE TABLE record_revisions (
	revision_id UUID NOT NULL,
	kind VARCHAR(32) NOT NULL,
	reported_outcome VARCHAR(64),
	explanation_md TEXT,
	PRIMARY KEY (revision_id),
	CONSTRAINT ck_record_kind CHECK (kind IN ('NOTE', 'IDEA', 'ATTEMPT', 'PROOF', 'DISCUSSION',
'COUNTEREXAMPLE', 'FORMALIZATION', 'COMPUTATION')),
	FOREIGN KEY(revision_id) REFERENCES object_revisions (id)
)
""")
    op.execute("""
CREATE TABLE public_releases (
	id UUID NOT NULL,
	ownership_scope_id UUID NOT NULL,
	object_revision_id UUID NOT NULL,
	contribution_id UUID NOT NULL,
	projection_version INTEGER NOT NULL,
	public_fields JSON NOT NULL,
	public_fields_digest VARCHAR(64) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT fk_public_releases_revision_scope FOREIGN KEY(object_revision_id,
ownership_scope_id) REFERENCES object_revisions (id, ownership_scope_id),
	CONSTRAINT uq_public_releases_scope_revision UNIQUE (ownership_scope_id,
object_revision_id),
	CONSTRAINT ck_public_releases_digest_length CHECK (length(public_fields_digest) = 64),
	FOREIGN KEY(ownership_scope_id) REFERENCES research_scopes (id),
	FOREIGN KEY(object_revision_id) REFERENCES object_revisions (id),
	FOREIGN KEY(contribution_id) REFERENCES contribution_envelopes (id)
)
""")
    op.execute("""
CREATE INDEX ix_public_releases_object_revision_id ON public_releases (object_revision_id)
""")
    op.execute("""
CREATE INDEX ix_public_releases_ownership_scope_id ON public_releases (ownership_scope_id)
""")
    op.execute("""
CREATE TABLE record_statement_links (
	record_revision_id UUID NOT NULL,
	statement_revision_id UUID NOT NULL,
	PRIMARY KEY (record_revision_id, statement_revision_id),
	FOREIGN KEY(record_revision_id) REFERENCES record_revisions (revision_id),
	FOREIGN KEY(statement_revision_id) REFERENCES statement_revisions (revision_id)
)
""")
    op.execute("""
CREATE TABLE contribution_entity_links (
	id UUID NOT NULL,
	envelope_id UUID NOT NULL,
	object_id UUID,
	revision_id UUID,
	relation_id UUID,
	comment_id UUID,
	ownership_scope_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_contribution_output_one_target CHECK ((CASE WHEN object_id IS NULL THEN 0 ELSE
1 END + CASE WHEN revision_id IS NULL THEN 0 ELSE 1 END + CASE WHEN relation_id IS NULL THEN
0 ELSE 1 END + CASE WHEN comment_id IS NULL THEN 0 ELSE 1 END) = 1),
	CONSTRAINT uq_output_object UNIQUE (envelope_id, object_id),
	CONSTRAINT uq_output_revision UNIQUE (envelope_id, revision_id),
	CONSTRAINT uq_output_relation UNIQUE (envelope_id, relation_id),
	CONSTRAINT uq_output_comment UNIQUE (envelope_id, comment_id),
	FOREIGN KEY(envelope_id) REFERENCES contribution_envelopes (id),
	FOREIGN KEY(object_id) REFERENCES research_objects (id),
	FOREIGN KEY(revision_id) REFERENCES object_revisions (id),
	FOREIGN KEY(relation_id) REFERENCES relation_assertions (id),
	FOREIGN KEY(comment_id) REFERENCES research_comments (id),
	FOREIGN KEY(ownership_scope_id) REFERENCES research_scopes (id)
)
""")
    op.execute("""
CREATE INDEX ix_contribution_entity_links_envelope_id ON contribution_entity_links
(envelope_id)
""")
    op.execute("""
ALTER TABLE research_objects ADD CONSTRAINT fk_research_objects_current_revision FOREIGN
KEY(current_revision_id, id) REFERENCES object_revisions (id, object_id)
""")
    op.execute("""
CREATE FUNCTION forbid_history_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'immutable history'; END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER object_revisions_immutable BEFORE UPDATE OR DELETE ON object_revisions FOR
EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER statement_revisions_immutable BEFORE UPDATE OR DELETE ON statement_revisions
FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER record_revisions_immutable BEFORE UPDATE OR DELETE ON record_revisions FOR
EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER record_statement_links_immutable BEFORE UPDATE OR DELETE ON
record_statement_links FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER relation_assertions_immutable BEFORE UPDATE OR DELETE ON relation_assertions
FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER research_comments_immutable BEFORE UPDATE OR DELETE ON research_comments FOR
EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER contribution_envelopes_immutable BEFORE UPDATE OR DELETE ON
contribution_envelopes FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER contribution_entity_links_immutable BEFORE UPDATE OR DELETE ON
contribution_entity_links FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER public_releases_immutable BEFORE UPDATE OR DELETE ON public_releases FOR EACH
ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER mutation_receipts_immutable BEFORE UPDATE OR DELETE ON mutation_receipts FOR
EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER platform_agent_versions_immutable BEFORE UPDATE OR DELETE ON
platform_agent_versions FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER agent_messages_immutable BEFORE UPDATE OR DELETE ON agent_messages FOR EACH
ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER agent_run_events_immutable BEFORE UPDATE OR DELETE ON agent_run_events FOR
EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER agent_run_usage_immutable BEFORE UPDATE OR DELETE ON agent_run_usage FOR EACH
ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER context_manifests_immutable BEFORE UPDATE OR DELETE ON context_manifests FOR
EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER proposal_change_decisions_immutable BEFORE UPDATE OR DELETE ON
proposal_change_decisions FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE TRIGGER proposal_decision_batches_immutable BEFORE UPDATE OR DELETE ON
proposal_decision_batches FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE FUNCTION protect_object_identity() RETURNS trigger AS $$
BEGIN
IF TG_OP = 'DELETE' OR NEW.ownership_scope_id IS DISTINCT FROM OLD.ownership_scope_id
 OR NEW.entity_class IS DISTINCT FROM OLD.entity_class OR NEW.kind IS DISTINCT FROM OLD.kind
 OR NEW.id IS DISTINCT FROM OLD.id OR NEW.contribution_id IS DISTINCT FROM OLD.contribution_id
 OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
 OR NEW.provenance_kind IS DISTINCT FROM OLD.provenance_kind OR NEW.created_at IS DISTINCT
FROM OLD.created_at THEN
 RAISE EXCEPTION 'immutable research identity'; END IF;
RETURN NEW; END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER research_identity_immutable BEFORE UPDATE OR DELETE ON research_objects FOR
EACH ROW EXECUTE FUNCTION protect_object_identity()
""")
    op.execute("""
CREATE FUNCTION validate_research_object() RETURNS trigger AS $$
DECLARE obj research_objects%ROWTYPE; rev object_revisions%ROWTYPE; base_number integer;
revision_to_check uuid;
BEGIN
IF TG_TABLE_NAME = 'research_objects' THEN
 SELECT * INTO obj FROM research_objects WHERE id = NEW.id;
 revision_to_check = obj.current_revision_id;
ELSE SELECT * INTO obj FROM research_objects WHERE id = NEW.object_id;
 revision_to_check = NEW.id; END IF;
IF obj.current_revision_id IS NULL OR NOT EXISTS (
 SELECT 1 FROM object_revisions WHERE id = obj.current_revision_id AND object_id = obj.id
) THEN RAISE EXCEPTION 'missing current revision'; END IF;
FOR rev IN SELECT * FROM object_revisions WHERE id = revision_to_check LOOP
 IF rev.number = 1 THEN
  IF rev.base_revision_id IS NOT NULL THEN RAISE EXCEPTION 'initial revision has a base'; END
IF;
 ELSE
  SELECT number INTO base_number FROM object_revisions WHERE id = rev.base_revision_id AND
object_id = obj.id;
  IF base_number IS DISTINCT FROM rev.number - 1 THEN RAISE EXCEPTION
'invalid revision predecessor'; END IF;
 END IF;
 IF obj.entity_class = 'STATEMENT' THEN
  IF NOT EXISTS (SELECT 1 FROM statement_revisions WHERE revision_id = rev.id AND kind =
obj.kind)
    OR EXISTS (SELECT 1 FROM record_revisions WHERE revision_id = rev.id)
  THEN RAISE EXCEPTION 'invalid statement metadata'; END IF;
 ELSIF obj.entity_class = 'RECORD' THEN
  IF NOT EXISTS (SELECT 1 FROM record_revisions WHERE revision_id = rev.id AND kind =
obj.kind)
    OR EXISTS (SELECT 1 FROM statement_revisions WHERE revision_id = rev.id)
  THEN RAISE EXCEPTION 'invalid record metadata'; END IF;
 ELSE RAISE EXCEPTION 'invalid research class';
 END IF;
END LOOP;
IF obj.current_revision_id IS DISTINCT FROM (
 SELECT id FROM object_revisions WHERE object_id = obj.id ORDER BY number DESC LIMIT 1
) THEN RAISE EXCEPTION 'current revision must be latest'; END IF;
RETURN NULL; END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE CONSTRAINT TRIGGER research_objects_complete AFTER INSERT OR UPDATE ON
research_objects DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
validate_research_object()
""")
    op.execute("""
CREATE CONSTRAINT TRIGGER object_revisions_complete AFTER INSERT OR UPDATE ON
object_revisions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
validate_research_object()
""")
    op.execute("""
CREATE FUNCTION protect_revision_extension() RETURNS trigger AS $$
DECLARE rev_id uuid; insertion_xid bigint;
BEGIN
IF TG_TABLE_NAME = 'record_statement_links' THEN rev_id = NEW.record_revision_id;
ELSE rev_id = NEW.revision_id; END IF;
SELECT xmin::text::bigint INTO insertion_xid FROM object_revisions WHERE id = rev_id;
IF insertion_xid IS DISTINCT FROM (txid_current() % 4294967296) THEN
 RAISE EXCEPTION 'revision attachments must be created with their revision';
END IF;
RETURN NEW; END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER statement_revisions_insert_boundary BEFORE INSERT ON statement_revisions FOR
EACH ROW EXECUTE FUNCTION protect_revision_extension()
""")
    op.execute("""
CREATE TRIGGER record_revisions_insert_boundary BEFORE INSERT ON record_revisions FOR EACH
ROW EXECUTE FUNCTION protect_revision_extension()
""")
    op.execute("""
CREATE TRIGGER record_statement_links_insert_boundary BEFORE INSERT ON record_statement_links
FOR EACH ROW EXECUTE FUNCTION protect_revision_extension()
""")
    op.execute("""
CREATE FUNCTION protect_outbox_content() RETURNS trigger AS $$
BEGIN
IF TG_OP = 'DELETE' OR
 (to_jsonb(NEW) - ARRAY['status','attempts','available_at','claimed_by','claimed_at'])
 IS DISTINCT FROM
 (to_jsonb(OLD) - ARRAY['status','attempts','available_at','claimed_by','claimed_at'])
THEN RAISE EXCEPTION 'immutable outbox content'; END IF;
RETURN NEW; END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER outbox_content_immutable BEFORE UPDATE OR DELETE ON outbox_events FOR EACH ROW
EXECUTE FUNCTION protect_outbox_content()
""")
    op.execute("""
CREATE FUNCTION validate_output_scope() RETURNS trigger AS $$
DECLARE target_scope uuid;
BEGIN
IF NEW.object_id IS NOT NULL THEN SELECT ownership_scope_id INTO target_scope FROM
research_objects WHERE id=NEW.object_id;
ELSIF NEW.revision_id IS NOT NULL THEN SELECT ownership_scope_id INTO target_scope FROM
object_revisions WHERE id=NEW.revision_id;
ELSIF NEW.relation_id IS NOT NULL THEN SELECT ownership_scope_id INTO target_scope FROM
relation_assertions WHERE id=NEW.relation_id;
ELSE SELECT ownership_scope_id INTO target_scope FROM research_comments WHERE
id=NEW.comment_id; END IF;
IF target_scope IS DISTINCT FROM NEW.ownership_scope_id OR NOT EXISTS (
 SELECT 1 FROM contribution_envelopes WHERE id = NEW.envelope_id AND ownership_scope_id =
target_scope
) THEN RAISE EXCEPTION 'output scope mismatch'; END IF;
RETURN NEW; END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER output_scope BEFORE INSERT ON contribution_entity_links FOR EACH ROW EXECUTE
FUNCTION validate_output_scope()
""")
    op.execute("""
INSERT INTO research_scopes (id, scope_kind, project_id, created_at) VALUES
('00000000-0000-0000-0000-000000000001', 'COMMONS', NULL, CURRENT_TIMESTAMP)
""")
    op.execute("""
INSERT INTO platform_agent_versions (id, agent_kind, version, display_name,
instructions_text, instructions_digest, execution_profile, created_at) VALUES
('a0000000-0000-4000-8000-000000000001','RESEARCHER', 1,
'Researcher','Explore mathematical claims and decompose problems.',
'efbf0fbcbca73cd083e72eb75acd75b6dd95499a6625593c180f6f97bf2361bd',
'TRUSTED_HOSTED', CURRENT_TIMESTAMP)
""")
    op.execute("""
INSERT INTO platform_agent_versions (id, agent_kind, version, display_name,
instructions_text, instructions_digest, execution_profile, created_at) VALUES
('a0000000-0000-4000-8000-000000000002','CRITIC', 1,
'Critic','Find gaps, hidden assumptions, and counterexamples.',
'30f5182e2241c01c8bcc7d990b2fedc9d31740a9dfc668ca93013d2f53a1bcb0',
'TRUSTED_HOSTED', CURRENT_TIMESTAMP)
""")

    op.execute("""
CREATE FUNCTION validate_research_contribution() RETURNS trigger AS $$
DECLARE envelope contribution_envelopes%ROWTYPE;
BEGIN
SELECT * INTO envelope FROM contribution_envelopes WHERE id=NEW.contribution_id;
IF envelope.ownership_scope_id IS DISTINCT FROM NEW.ownership_scope_id THEN
 RAISE EXCEPTION 'research contribution scope mismatch';
END IF;
IF TG_TABLE_NAME <> 'public_releases' THEN
 IF (NEW.provenance_kind = 'HUMAN_DIRECT' AND
     (envelope.actor_kind <> 'HUMAN' OR
      envelope.human_user_id IS DISTINCT FROM NEW.created_by_user_id))
 OR (NEW.provenance_kind = 'AGENT_PROPOSAL' AND
     (envelope.actor_kind <> 'AGENT' OR envelope.proposal_change_id IS NULL OR
      envelope.decided_by_user_id IS DISTINCT FROM NEW.created_by_user_id))
 OR (NEW.provenance_kind = 'AGENT_DIRECT' AND
     (envelope.actor_kind <> 'AGENT' OR envelope.proposal_change_id IS NOT NULL OR
      envelope.sponsor_user_id IS DISTINCT FROM NEW.created_by_user_id)) THEN
  RAISE EXCEPTION 'research attribution mismatch';
 END IF;
END IF;
RETURN NEW; END; $$ LANGUAGE plpgsql
""")
    for table in (
        "research_objects",
        "object_revisions",
        "relation_assertions",
        "research_comments",
        "public_releases",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_contribution BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION validate_research_contribution()"
        )


def downgrade() -> None:
    raise RuntimeError("Baseline downgrade is unsupported; use an explicitly disposable database.")
