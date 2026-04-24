create schema if not exists public;

create table if not exists public.conversation_turns (
    id text primary key,
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
