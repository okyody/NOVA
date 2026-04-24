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
    trace_id text,
    ts timestamptz not null,
    category text not null,
    reason text,
    blocked_text text,
    payload_json jsonb not null default '{}'::jsonb
);

create index if not exists idx_safety_events_ts on public.safety_events (ts desc);
create index if not exists idx_safety_events_trace on public.safety_events (trace_id);
