create schema if not exists public;

create table if not exists public.conversation_turns (
    id text primary key,
    runtime_instance text not null,
    session_id text not null,
    event_type text not null,
    source text not null,
    trace_id text,
    ts timestamptz not null,
    role text not null,
    viewer_id text,
    viewer_name text,
    text_content text,
    payload_json jsonb not null default '{}'::jsonb
);

create index if not exists idx_conversation_turns_ts on public.conversation_turns (ts desc);
create index if not exists idx_conversation_turns_trace on public.conversation_turns (trace_id);

create table if not exists public.safety_events (
    id text primary key,
    runtime_instance text not null,
    session_id text not null,
    trace_id text,
    ts timestamptz not null,
    category text not null,
    reason text,
    blocked_text text,
    payload_json jsonb not null default '{}'::jsonb
);

create index if not exists idx_safety_events_ts on public.safety_events (ts desc);
create index if not exists idx_safety_events_trace on public.safety_events (trace_id);

create table if not exists public.runtime_sessions (
    id text primary key,
    runtime_instance text not null,
    status text not null,
    role text not null,
    character text,
    llm_model text,
    started_at timestamptz not null,
    stopped_at timestamptz,
    last_activity_at timestamptz,
    summary_json jsonb not null default '{}'::jsonb
);

create table if not exists public.runtime_viewers (
    id text primary key,
    runtime_instance text not null,
    session_id text not null,
    platform text,
    username text,
    is_member boolean not null default false,
    gift_total double precision not null default 0,
    interaction_count integer not null default 0,
    last_seen_at timestamptz,
    last_event_type text,
    last_message text,
    payload_json jsonb not null default '{}'::jsonb
);

create table if not exists public.audit_logs (
    id text primary key,
    runtime_instance text not null,
    ts timestamptz not null,
    action text not null,
    resource_type text not null,
    resource_id text,
    detail_json jsonb not null default '{}'::jsonb
);

create table if not exists public.tenants (
    id text primary key,
    name text not null,
    slug text not null unique,
    status text not null default 'active',
    plan text not null default 'enterprise',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.roles (
    id text primary key,
    tenant_id text not null,
    name text not null,
    scope text not null,
    description text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.config_revisions (
    id text primary key,
    tenant_id text not null,
    resource_type text not null,
    resource_id text not null,
    revision_no integer not null,
    status text not null default 'draft',
    config_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists public.permissions (
    id text primary key,
    code text not null unique,
    resource text not null,
    action text not null,
    description text,
    created_at timestamptz not null default now()
);

create table if not exists public.role_permissions (
    role_id text not null,
    permission_id text not null,
    created_at timestamptz not null default now(),
    primary key (role_id, permission_id)
);

create table if not exists public.users (
    id text primary key,
    tenant_id text not null,
    email text not null,
    display_name text,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.user_roles (
    user_id text not null,
    role_id text not null,
    created_at timestamptz not null default now(),
    primary key (user_id, role_id)
);

create index if not exists idx_runtime_sessions_started_at on public.runtime_sessions (started_at desc);
create index if not exists idx_runtime_viewers_session_id on public.runtime_viewers (session_id);
create index if not exists idx_audit_logs_ts on public.audit_logs (ts desc);
create index if not exists idx_roles_tenant_id on public.roles (tenant_id);
create index if not exists idx_config_revisions_resource on public.config_revisions (resource_type, resource_id, revision_no desc);
create index if not exists idx_permissions_code on public.permissions (code);
create index if not exists idx_users_tenant_id on public.users (tenant_id);
