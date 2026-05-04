"""
NOVA Studio — Web Management Panel
=====================================
Built into the FastAPI server. No build tools required.
Pure HTML + Tailwind CDN + vanilla JS.

Pages:
  /studio/         — Main dashboard (real-time event stream, emotion gauge)
  /studio/config   — Configuration editor
  /studio/logs     — Live log viewer
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

log = logging.getLogger("nova.studio")

router = APIRouter(prefix="/studio", tags=["studio"])

# ─── Dashboard HTML ─────────────────────────────────────────────────────────────

STUDIO_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NOVA Studio</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body { background: #0f1117; color: #e8eaf0; font-family: 'SF Mono', 'Cascadia Code', monospace; }
  .card { background: #181c24; border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; }
  .pulse { animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse { 0%,100% { opacity: 0.6; } 50% { opacity: 1; } }
  .event-row { border-bottom: 1px solid rgba(255,255,255,0.05); padding: 4px 8px; font-size: 12px; }
  .tag { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; margin-right: 4px; }
  .tag-chat { background: rgba(59,130,246,0.2); color: #60a5fa; }
  .tag-gift { background: rgba(245,158,11,0.2); color: #fbbf24; }
  .tag-safety { background: rgba(239,68,68,0.2); color: #f87171; }
  .tag-cognitive { background: rgba(139,92,246,0.2); color: #a78bfa; }
  .tag-generation { background: rgba(20,184,166,0.2); color: #2dd4bf; }
  .gauge { width: 120px; height: 120px; border-radius: 50%; border: 4px solid rgba(255,255,255,0.1); position: relative; overflow: hidden; }
  .gauge-fill { position: absolute; bottom: 0; left: 0; right: 0; transition: height 0.3s, background 0.3s; border-radius: 0 0 56px 56px; }
  #status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .dot-ok { background: #22c55e; }
  .dot-err { background: #ef4444; }
</style>
</head>
<body class="min-h-screen">
<div class="flex h-screen">
  <!-- Sidebar -->
  <div class="w-48 border-r border-white/5 p-4 flex flex-col gap-2">
    <div class="text-sm font-bold mb-4 text-white/80">NOVA Studio</div>
    <a href="#" onclick="showTab('dashboard')" class="text-xs text-white/60 hover:text-white/90 px-2 py-1 rounded hover:bg-white/5">Dashboard</a>
    <a href="#" onclick="showTab('events')" class="text-xs text-white/60 hover:text-white/90 px-2 py-1 rounded hover:bg-white/5">Events</a>
    <a href="#" onclick="showTab('config')" class="text-xs text-white/60 hover:text-white/90 px-2 py-1 rounded hover:bg-white/5">Config</a>
    <a href="#" onclick="showTab('control')" class="text-xs text-white/60 hover:text-white/90 px-2 py-1 rounded hover:bg-white/5">Control</a>
    <div class="mt-auto text-[10px] text-white/30">v1.0.0</div>
  </div>

  <!-- Main -->
  <div class="flex-1 overflow-auto p-6">
    <!-- Header -->
    <div class="flex items-center gap-3 mb-6">
      <span id="status-dot" class="dot-ok"></span>
      <span class="text-sm font-semibold" id="char-name">NOVA</span>
      <div class="ml-auto flex items-center gap-2">
        <input id="login-user-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="user id">
        <button onclick="studioLogin()" class="bg-blue-500/20 hover:bg-blue-500/30 text-blue-200 rounded px-2 py-1 text-xs">Login</button>
        <button onclick="studioLogout()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Logout</button>
        <span class="text-xs text-white/50" id="current-user">anonymous</span>
      </div>
      <span class="text-xs text-white/40" id="uptime">—</span>
    </div>

    <!-- Dashboard Tab -->
    <div id="tab-dashboard">
      <div class="grid grid-cols-4 gap-4 mb-6">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-1">Events/sec</div>
          <div class="text-2xl font-bold" id="eps">0</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-1">Safety Blocks</div>
          <div class="text-2xl font-bold" id="blocks">0</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-1">Queue Depth</div>
          <div class="text-2xl font-bold" id="queue">0</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-1">Platforms</div>
          <div class="text-2xl font-bold" id="platforms">0</div>
        </div>
      </div>

      <div class="grid grid-cols-4 gap-4 mb-6">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-1">Consumer Lag</div>
          <div class="text-2xl font-bold" id="consumer-lag">0</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-1">Pending</div>
          <div class="text-2xl font-bold" id="pending">0</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-1">Retries</div>
          <div class="text-2xl font-bold" id="retries">0</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-1">DLQ</div>
          <div class="text-2xl font-bold" id="dlq">0</div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <!-- Emotion Gauge -->
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Emotion State</div>
          <div class="flex items-center gap-6">
            <div class="gauge">
              <div class="gauge-fill" id="emotion-gauge" style="height:30%;background:#6366f1;"></div>
            </div>
            <div>
              <div class="text-lg font-bold" id="emotion-label">NEUTRAL</div>
              <div class="text-xs text-white/40" id="emotion-detail">V:0.00 A:0.30</div>
            </div>
          </div>
        </div>

        <!-- Heat Level -->
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Stream Heat</div>
          <div class="text-lg font-bold" id="heat-level">NORMAL</div>
          <div class="text-xs text-white/40" id="heat-detail">Chat: 0/min | Gifts: 0/min</div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4 mt-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Persisted History</div>
          <div class="text-xs text-white/40 mb-2">Conversation <span id="conv-count">0</span> | Safety <span id="safety-count">0</span></div>
          <div id="history-preview" class="max-h-[220px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Runtime</div>
          <div class="text-xs text-white/60">Role: <span id="runtime-role">unknown</span></div>
          <div class="text-xs text-white/60">Instance: <span id="runtime-instance">unknown</span></div>
          <div class="text-xs text-white/60">Session: <span id="runtime-session">unknown</span></div>
          <div class="text-xs text-white/60">Hot State: <span id="runtime-hot">false</span></div>
        </div>
      </div>
    </div>

    <!-- Events Tab -->
    <div id="tab-events" style="display:none">
      <div class="card overflow-hidden">
        <div class="p-3 border-b border-white/5 flex items-center justify-between">
          <span class="text-xs text-white/60">Live Event Stream</span>
          <button onclick="clearEvents()" class="text-[10px] text-white/40 hover:text-white/60">Clear</button>
        </div>
        <div id="event-list" class="max-h-[600px] overflow-auto"></div>
      </div>
    </div>

    <!-- Config Tab -->
    <div id="tab-config" style="display:none">
      <div class="grid grid-cols-2 gap-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Settings Workbench</div>
          <div class="text-xs text-white/40 mb-3">Config File: <span id="config-path">loading…</span></div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">Core Runtime</div>
              <div class="flex flex-col gap-2">
                <input id="cfg-port" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="port">
                <input id="cfg-runtime-role" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="role (all/api/perception/cognitive/generation)">
                <label class="text-xs text-white/70 flex items-center gap-2"><input type="checkbox" id="cfg-auth-enabled"> Auth Enabled</label>
              </div>
            </div>
            <div>
              <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">LLM</div>
              <div class="flex flex-col gap-2">
                <input id="cfg-llm-base-url" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="LLM base URL">
                <input id="cfg-llm-model" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="LLM model">
              </div>
            </div>
            <div>
              <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">Character & Voice</div>
              <div class="flex flex-col gap-2">
                <input id="cfg-character-path" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="character path">
                <input id="cfg-voice-backend" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="voice backend">
                <input id="cfg-voice-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="voice id">
              </div>
            </div>
            <div>
              <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">Knowledge & Persistence</div>
              <div class="flex flex-col gap-2">
                <label class="text-xs text-white/70 flex items-center gap-2"><input type="checkbox" id="cfg-knowledge-enabled"> Knowledge Enabled</label>
                <input id="cfg-persistence-backend" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="persistence backend">
                <input id="cfg-postgres-url" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="postgres url">
                <input id="cfg-redis-url" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="redis url">
              </div>
            </div>
          </div>
          <div class="flex gap-2 mt-4">
            <button onclick="loadConfigForm()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Reload Settings</button>
            <button onclick="saveConfigForm()" class="bg-green-500/20 hover:bg-green-500/30 text-green-200 rounded px-2 py-1 text-xs">Save Config</button>
            <button onclick="reloadCharacterConfig()" class="bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-200 rounded px-2 py-1 text-xs">Reload Character</button>
          </div>
          <div class="text-xs text-white/40 mt-3" id="config-save-status">Settings are persisted to nova.config.json. Runtime restart is only required for structural changes.</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Effective Config Summary</div>
          <div class="text-xs text-white/60 mb-3" id="config-display">Loading…</div>
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">Advanced JSON Preview</div>
          <textarea id="config-json-preview" class="w-full h-[420px] bg-black/20 border border-white/10 rounded px-2 py-2 text-xs text-white/70"></textarea>
        </div>
      </div>
    </div>

    <!-- Control Tab -->
    <div id="tab-control" style="display:none">
      <div class="grid grid-cols-2 gap-4 mb-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Workbench</div>
          <div class="text-xs text-white/60">User: <span id="auth-user-id">anonymous</span></div>
          <div class="text-xs text-white/60">Tenant Scope: <span id="auth-tenant-scope">n/a</span></div>
          <div class="text-xs text-white/60">Roles: <span id="auth-role-list">none</span></div>
          <div class="text-xs text-white/60 mt-2">Permissions</div>
          <div id="auth-permission-list" class="text-xs text-white/70 mt-1 max-h-[100px] overflow-auto"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Resource Navigation</div>
          <div class="flex flex-wrap gap-2">
            <button onclick="showTab('control'); scrollIntoViewId('tenant-list')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Tenants</button>
            <button onclick="showTab('control'); scrollIntoViewId('user-list')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Users</button>
            <button onclick="showTab('control'); scrollIntoViewId('role-list')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Roles</button>
            <button onclick="showTab('control'); scrollIntoViewId('permission-list')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Permissions</button>
            <button onclick="showTab('control'); scrollIntoViewId('revision-list')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Revisions</button>
            <button onclick="showTab('events')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Runtime Events</button>
          </div>
          <div class="text-xs text-white/40 mt-4">Use the control log below for API failures and operation traces.</div>
        </div>
      </div>
      <div class="grid grid-cols-3 gap-4 mb-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Create Tenant</div>
          <div class="flex flex-col gap-2">
            <input id="tenant-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="tenant id">
            <input id="tenant-name" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="tenant name">
            <input id="tenant-slug" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="tenant slug">
            <input id="tenant-plan" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="plan (enterprise/pro)">
            <button onclick="createTenant()" class="bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-200 rounded px-2 py-1 text-xs">Create Tenant</button>
          </div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Create Role</div>
          <div class="flex flex-col gap-2">
            <input id="role-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="role id">
            <input id="role-tenant-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="tenant id">
            <input id="role-name" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="role name">
            <input id="role-scope" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="scope (tenant/system)">
            <input id="role-description" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="description">
            <button onclick="createRole()" class="bg-teal-500/20 hover:bg-teal-500/30 text-teal-200 rounded px-2 py-1 text-xs">Create Role</button>
          </div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Create Revision</div>
          <div class="flex flex-col gap-2">
            <input id="revision-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="revision id">
            <input id="revision-tenant-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="tenant id">
            <input id="revision-resource-type" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="resource type">
            <input id="revision-resource-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="resource id">
            <input id="revision-no" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="revision no">
            <textarea id="revision-config-json" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs h-20" placeholder='{"key":"value"}'></textarea>
            <div class="flex gap-2">
              <button onclick="createRevision()" class="bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 rounded px-2 py-1 text-xs flex-1">Create Draft</button>
              <button onclick="publishRevision()" class="bg-green-500/20 hover:bg-green-500/30 text-green-200 rounded px-2 py-1 text-xs flex-1">Publish</button>
              <button onclick="rollbackRevision()" class="bg-red-500/20 hover:bg-red-500/30 text-red-200 rounded px-2 py-1 text-xs flex-1">Rollback</button>
            </div>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-3 gap-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Tenants</div>
          <div id="tenant-list" class="max-h-[320px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Roles</div>
          <div id="role-list" class="max-h-[320px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Config Revisions</div>
          <div id="revision-list" class="max-h-[320px] overflow-auto text-xs text-white/70"></div>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-4 mt-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Permissions</div>
          <div class="flex flex-col gap-2 mb-3">
            <input id="permission-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="permission id">
            <input id="permission-code" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="code e.g. tenant.read">
            <input id="permission-resource" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="resource">
            <input id="permission-action" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="action">
            <input id="permission-description" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="description">
            <button onclick="createPermission()" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-2 py-1 text-xs">Create Permission</button>
          </div>
          <div id="permission-list" class="max-h-[240px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Role Permission Binding</div>
          <div class="flex flex-col gap-2 mb-3">
            <input id="binding-role-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="role id">
            <textarea id="binding-permission-ids" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs h-20" placeholder="permission ids, comma-separated"></textarea>
            <div class="flex gap-2">
              <button onclick="setRolePermissions()" class="bg-fuchsia-500/20 hover:bg-fuchsia-500/30 text-fuchsia-200 rounded px-2 py-1 text-xs flex-1">Bind Permissions</button>
              <button onclick="loadRolePermissions()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs flex-1">Load Current</button>
            </div>
          </div>
          <div id="role-permission-list" class="max-h-[240px] overflow-auto text-xs text-white/70"></div>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-4 mt-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Users</div>
          <div class="flex flex-col gap-2 mb-3">
            <input id="user-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="user id">
            <input id="user-tenant-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="tenant id">
            <input id="user-email" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="email">
            <input id="user-display-name" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="display name">
            <button onclick="createUser()" class="bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-200 rounded px-2 py-1 text-xs">Create User</button>
          </div>
          <div id="user-list" class="max-h-[240px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">User Role Binding</div>
          <div class="flex flex-col gap-2 mb-3">
            <input id="binding-user-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="user id">
            <textarea id="binding-role-ids" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs h-20" placeholder="role ids, comma-separated"></textarea>
            <div class="flex gap-2">
              <button onclick="setUserRoles()" class="bg-lime-500/20 hover:bg-lime-500/30 text-lime-200 rounded px-2 py-1 text-xs flex-1">Bind Roles</button>
              <button onclick="loadUserRoles()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs flex-1">Load Current</button>
            </div>
          </div>
          <div id="user-role-list" class="max-h-[240px] overflow-auto text-xs text-white/70"></div>
        </div>
      </div>
      <div class="card p-4 mt-4">
        <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Control Log</div>
        <div id="control-log" class="max-h-[180px] overflow-auto text-xs text-white/60"></div>
      </div>
    </div>
  </div>
</div>

<script>
const ws = new WebSocket(`ws://${location.host}/ws/control`);
const eventList = document.getElementById('event-list');
const MAX_EVENTS = 200;
let startTime = Date.now();
let authToken = localStorage.getItem('nova_studio_token') || '';

function showTab(name) {
  ['dashboard','events','config','control'].forEach(t => {
    document.getElementById('tab-'+t).style.display = t===name ? '' : 'none';
  });
}

function clearEvents() { eventList.innerHTML = ''; }
function scrollIntoViewId(id) {
  const node = document.getElementById(id);
  if (node) node.scrollIntoView({behavior: 'smooth', block: 'start'});
}
function controlLog(message) {
  const log = document.getElementById('control-log');
  const row = document.createElement('div');
  row.className = 'event-row';
  row.textContent = `${new Date().toLocaleTimeString()} ${message}`;
  log.prepend(row);
  while (log.children.length > 50) log.lastChild.remove();
}

function authHeaders() {
  return authToken ? {'Authorization': `Bearer ${authToken}`} : {};
}

function tagClass(type) {
  if (type.startsWith('platform.')) return 'tag-chat';
  if (type.includes('gift') || type.includes('super_chat')) return 'tag-gift';
  if (type.includes('safety')) return 'tag-safety';
  if (type.startsWith('cognitive.')) return 'tag-cognitive';
  if (type.startsWith('generation.')) return 'tag-generation';
  return '';
}

ws.onmessage = (e) => {
  try {
    const msg = JSON.parse(e.data);
    const type = msg.type || '';

    // Update event list
    const row = document.createElement('div');
    row.className = 'event-row';
    const ts = new Date(msg.ts || Date.now()).toLocaleTimeString();
    const tag = tagClass(type);
    row.innerHTML = `<span class="text-white/30">${ts}</span> <span class="tag ${tag}">${type.split('.').pop()}</span> <span class="text-white/50">${truncate(JSON.stringify(msg.payload||{}), 80)}</span>`;
    eventList.prepend(row);
    while (eventList.children.length > MAX_EVENTS) eventList.lastChild.remove();

    // Update dashboard
    if (type === 'cognitive.emotion_state') updateEmotion(msg.payload);
    if (type === 'perception.context_update') updateHeat(msg.payload);
  } catch(err) {}
};

ws.onopen = () => {
  document.getElementById('status-dot').className = 'dot-ok';
  ws.send(JSON.stringify({cmd:'ping'}));
};
ws.onclose = () => {
  document.getElementById('status-dot').className = 'dot-err';
};

function updateEmotion(p) {
  if (!p) return;
  const label = (p.label || 'NEUTRAL').toUpperCase();
  const valence = p.valence || 0;
  const arousal = p.arousal || 0.3;
  document.getElementById('emotion-label').textContent = label;
  document.getElementById('emotion-detail').textContent = `V:${valence.toFixed(2)} A:${arousal.toFixed(2)}`;
  const fill = document.getElementById('emotion-gauge');
  fill.style.height = `${Math.max(10, arousal * 100)}%`;
  const color = valence > 0.2 ? '#22c55e' : valence < -0.2 ? '#ef4444' : '#6366f1';
  fill.style.background = color;
}

function updateHeat(p) {
  if (!p) return;
  document.getElementById('heat-level').textContent = (p.heat_level || 'NORMAL').toUpperCase();
  document.getElementById('heat-detail').textContent = `Chat: ${p.chat_rate||0}/min | Gifts: ${p.gift_rate||0}/min`;
}

function truncate(s, n) { return s.length > n ? s.slice(0, n) + '…' : s; }

async function postJson(url, method, payload) {
  const response = await fetch(url, {
    method,
    headers: {'Content-Type': 'application/json', ...authHeaders()},
    body: JSON.stringify(payload || {})
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.reason || data.status || 'request failed');
  }
  return data;
}

async function getJson(url) {
  const response = await fetch(url, {headers: {...authHeaders()}});
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || data.reason || data.status || 'request failed');
  }
  return data;
}

function configSummary(config) {
  return [
    `Port: ${config.port ?? '8765'}`,
    `Role: ${config.runtime?.role || 'all'}`,
    `Auth: ${config.auth?.enabled ? 'enabled' : 'disabled'}`,
    `LLM: ${config.llm?.model || 'n/a'}`,
    `Character: ${config.character?.path || 'n/a'}`,
    `Voice: ${config.voice?.backend || 'n/a'} / ${config.voice?.voice_id || 'n/a'}`,
    `Knowledge: ${config.knowledge?.enabled ? 'enabled' : 'disabled'}`,
    `Persistence: ${config.persistence?.backend || 'n/a'}`,
  ].join(' | ');
}

function fillConfigForm(configPath, config) {
  document.getElementById('config-path').textContent = configPath || 'nova.config.json';
  document.getElementById('config-display').textContent = configSummary(config || {});
  document.getElementById('config-json-preview').value = JSON.stringify(config || {}, null, 2);
  document.getElementById('cfg-port').value = config.port ?? 8765;
  document.getElementById('cfg-runtime-role').value = config.runtime?.role || 'all';
  document.getElementById('cfg-auth-enabled').checked = !!config.auth?.enabled;
  document.getElementById('cfg-llm-base-url').value = config.llm?.base_url || '';
  document.getElementById('cfg-llm-model').value = config.llm?.model || '';
  document.getElementById('cfg-character-path').value = config.character?.path || '';
  document.getElementById('cfg-voice-backend').value = config.voice?.backend || '';
  document.getElementById('cfg-voice-id').value = config.voice?.voice_id || '';
  document.getElementById('cfg-knowledge-enabled').checked = !!config.knowledge?.enabled;
  document.getElementById('cfg-persistence-backend').value = config.persistence?.backend || 'json';
  document.getElementById('cfg-postgres-url').value = config.persistence?.postgres_url || '';
  document.getElementById('cfg-redis-url').value = config.persistence?.redis_url || '';
}

function collectConfigPayload() {
  return {
    port: Number(document.getElementById('cfg-port').value || '8765'),
    llm: {
      base_url: document.getElementById('cfg-llm-base-url').value.trim(),
      model: document.getElementById('cfg-llm-model').value.trim(),
    },
    voice: {
      backend: document.getElementById('cfg-voice-backend').value.trim() || 'edge_tts',
      voice_id: document.getElementById('cfg-voice-id').value.trim(),
    },
    character: {
      path: document.getElementById('cfg-character-path').value.trim(),
    },
    knowledge: {
      enabled: document.getElementById('cfg-knowledge-enabled').checked,
    },
    persistence: {
      backend: document.getElementById('cfg-persistence-backend').value.trim() || 'json',
      postgres_url: document.getElementById('cfg-postgres-url').value.trim(),
      redis_url: document.getElementById('cfg-redis-url').value.trim(),
    },
    auth: {
      enabled: document.getElementById('cfg-auth-enabled').checked,
    },
    runtime: {
      role: document.getElementById('cfg-runtime-role').value.trim() || 'all',
    },
  };
}

async function loadConfigForm() {
  try {
    const result = await getJson('/api/config/current');
    fillConfigForm(result.config_path, result.config_json || {});
    document.getElementById('config-save-status').textContent = 'Settings loaded from disk.';
  } catch (err) {
    controlLog(`config load failed: ${err.message}`);
    document.getElementById('config-save-status').textContent = `Load failed: ${err.message}`;
  }
}

async function saveConfigForm() {
  try {
    const payload = {config_json: collectConfigPayload()};
    const result = await postJson('/api/config/current', 'POST', payload);
    document.getElementById('config-save-status').textContent =
      result.restart_required
        ? 'Config saved. Restart required for some changes.'
        : 'Config saved. Live settings updated where safe.';
    controlLog(`config saved: ${result.config_path}`);
    await loadConfigForm();
  } catch (err) {
    controlLog(`config save failed: ${err.message}`);
    document.getElementById('config-save-status').textContent = `Save failed: ${err.message}`;
  }
}

async function reloadCharacterConfig() {
  try {
    const result = await postJson('/api/config/reload', 'POST', {});
    document.getElementById('config-save-status').textContent = `Character reloaded: ${result.character || 'ok'}`;
    controlLog(`character reload ok: ${result.character || 'ok'}`);
  } catch (err) {
    controlLog(`character reload failed: ${err.message}`);
    document.getElementById('config-save-status').textContent = `Reload failed: ${err.message}`;
  }
}

function renderList(elementId, items, fields) {
  const target = document.getElementById(elementId);
  target.innerHTML = '';
  (items || []).forEach((item) => {
    const row = document.createElement('div');
    row.className = 'event-row';
    row.textContent = fields.map((field) => `${field}: ${item[field] ?? ''}`).join(' | ');
    target.appendChild(row);
  });
}

async function refreshControlPlane() {
  try {
    const [tenants, roles, revisions, permissions, users] = await Promise.all([
      getJson('/api/control/tenants?limit=20&offset=0'),
      getJson('/api/control/roles?limit=20&offset=0'),
      getJson('/api/control/config-revisions?limit=20&offset=0'),
      getJson('/api/control/permissions?limit=20&offset=0'),
      getJson('/api/control/users?limit=20&offset=0'),
    ]);
    renderList('tenant-list', tenants.items || [], ['id', 'slug', 'status', 'plan']);
    renderList('role-list', roles.items || [], ['id', 'tenant_id', 'name', 'scope']);
    renderList('revision-list', revisions.items || [], ['id', 'resource_type', 'resource_id', 'revision_no', 'status']);
    renderList('permission-list', permissions.items || [], ['id', 'code', 'resource', 'action']);
    renderList('user-list', users.items || [], ['id', 'tenant_id', 'email', 'status']);
  } catch (err) {
    controlLog(`refresh failed: ${err.message}`);
  }
}

async function createTenant() {
  try {
    const payload = {
      id: document.getElementById('tenant-id').value,
      name: document.getElementById('tenant-name').value,
      slug: document.getElementById('tenant-slug').value,
      plan: document.getElementById('tenant-plan').value || 'enterprise',
    };
    const result = await postJson('/api/control/tenants', 'POST', payload);
    controlLog(`tenant created: ${result.id}`);
    await refreshControlPlane();
  } catch (err) {
    controlLog(`tenant create failed: ${err.message}`);
  }
}

async function createRole() {
  try {
    const payload = {
      id: document.getElementById('role-id').value,
      tenant_id: document.getElementById('role-tenant-id').value,
      name: document.getElementById('role-name').value,
      scope: document.getElementById('role-scope').value,
      description: document.getElementById('role-description').value,
    };
    const result = await postJson('/api/control/roles', 'POST', payload);
    controlLog(`role created: ${result.id}`);
    await refreshControlPlane();
  } catch (err) {
    controlLog(`role create failed: ${err.message}`);
  }
}

async function createPermission() {
  try {
    const payload = {
      id: document.getElementById('permission-id').value,
      code: document.getElementById('permission-code').value,
      resource: document.getElementById('permission-resource').value,
      action: document.getElementById('permission-action').value,
      description: document.getElementById('permission-description').value,
    };
    const result = await postJson('/api/control/permissions', 'POST', payload);
    controlLog(`permission created: ${result.id}`);
    await refreshControlPlane();
  } catch (err) {
    controlLog(`permission create failed: ${err.message}`);
  }
}

async function createUser() {
  try {
    const payload = {
      id: document.getElementById('user-id').value,
      tenant_id: document.getElementById('user-tenant-id').value,
      email: document.getElementById('user-email').value,
      display_name: document.getElementById('user-display-name').value,
    };
    const result = await postJson('/api/control/users', 'POST', payload);
    controlLog(`user created: ${result.id}`);
    await refreshControlPlane();
  } catch (err) {
    controlLog(`user create failed: ${err.message}`);
  }
}

function currentRevisionPayload() {
  let config = {};
  const raw = document.getElementById('revision-config-json').value.trim();
  if (raw) config = JSON.parse(raw);
  return {
    id: document.getElementById('revision-id').value,
    tenant_id: document.getElementById('revision-tenant-id').value,
    resource_type: document.getElementById('revision-resource-type').value,
    resource_id: document.getElementById('revision-resource-id').value,
    revision_no: Number(document.getElementById('revision-no').value || '1'),
    config_json: config,
  };
}

async function createRevision() {
  try {
    const payload = currentRevisionPayload();
    const result = await postJson('/api/control/config-revisions', 'POST', payload);
    controlLog(`revision created: ${result.id}`);
    await refreshControlPlane();
  } catch (err) {
    controlLog(`revision create failed: ${err.message}`);
  }
}

async function publishRevision() {
  try {
    const revisionId = document.getElementById('revision-id').value;
    const result = await postJson(`/api/control/config-revisions/${revisionId}/publish`, 'POST', {operator: 'studio'});
    controlLog(`revision published: ${result.id}`);
    await refreshControlPlane();
  } catch (err) {
    controlLog(`revision publish failed: ${err.message}`);
  }
}

async function rollbackRevision() {
  try {
    const revisionId = document.getElementById('revision-id').value;
    const result = await postJson(`/api/control/config-revisions/${revisionId}/rollback`, 'POST', {operator: 'studio'});
    controlLog(`revision rolled back: ${result.id}`);
    await refreshControlPlane();
  } catch (err) {
    controlLog(`revision rollback failed: ${err.message}`);
  }
}

async function loadRolePermissions() {
  try {
    const roleId = document.getElementById('binding-role-id').value;
    const result = await getJson(`/api/control/roles/${roleId}/permissions?limit=50&offset=0`);
    renderList('role-permission-list', result.items || [], ['permission_id', 'code', 'resource', 'action']);
  } catch (err) {
    controlLog(`load role permissions failed: ${err.message}`);
  }
}

async function setRolePermissions() {
  try {
    const roleId = document.getElementById('binding-role-id').value;
    const permissionIds = document.getElementById('binding-permission-ids').value
      .split(',')
      .map(v => v.trim())
      .filter(Boolean);
    const result = await postJson(`/api/control/roles/${roleId}/permissions`, 'PUT', {permission_ids: permissionIds});
    controlLog(`role permissions updated: ${result.id} (${result.permission_count})`);
    await loadRolePermissions();
  } catch (err) {
    controlLog(`bind permissions failed: ${err.message}`);
  }
}

async function loadUserRoles() {
  try {
    const userId = document.getElementById('binding-user-id').value;
    const result = await getJson(`/api/control/users/${userId}/roles?limit=50&offset=0`);
    renderList('user-role-list', result.items || [], ['role_id', 'name', 'scope']);
  } catch (err) {
    controlLog(`load user roles failed: ${err.message}`);
  }
}

async function setUserRoles() {
  try {
    const userId = document.getElementById('binding-user-id').value;
    const roleIds = document.getElementById('binding-role-ids').value
      .split(',')
      .map(v => v.trim())
      .filter(Boolean);
    const result = await postJson(`/api/control/users/${userId}/roles`, 'PUT', {role_ids: roleIds});
    controlLog(`user roles updated: ${result.id} (${result.role_count})`);
    await loadUserRoles();
  } catch (err) {
    controlLog(`bind user roles failed: ${err.message}`);
  }
}

async function refreshCurrentUser() {
  if (!authToken) {
    const current = document.getElementById('current-user');
    if (current) current.textContent = 'anonymous';
    document.getElementById('auth-user-id').textContent = 'anonymous';
    document.getElementById('auth-tenant-scope').textContent = 'n/a';
    document.getElementById('auth-role-list').textContent = 'none';
    document.getElementById('auth-permission-list').innerHTML = '';
    return;
  }
  try {
    const me = await getJson('/api/auth/me');
    const user = me.user || {};
    const current = document.getElementById('current-user');
    if (current) {
      const tenant = user.tenant_id || (user.tenant_ids || []).join(',');
      current.textContent = `${user.id || 'unknown'} @ ${tenant || 'n/a'}`;
    }
    document.getElementById('auth-user-id').textContent = user.id || 'unknown';
    document.getElementById('auth-tenant-scope').textContent = user.tenant_id || (user.tenant_ids || []).join(',') || 'n/a';
    document.getElementById('auth-role-list').textContent = (user.roles || []).join(', ') || 'none';
    const permList = document.getElementById('auth-permission-list');
    permList.innerHTML = '';
    (user.permissions || []).forEach((permission) => {
      const row = document.createElement('div');
      row.className = 'event-row';
      row.textContent = permission;
      permList.appendChild(row);
    });
  } catch (err) {
    controlLog(`auth refresh failed: ${err.message}`);
  }
}

async function studioLogin() {
  try {
    const userId = document.getElementById('login-user-id').value.trim();
    const result = await postJson('/api/auth/token', 'POST', {user_id: userId});
    authToken = result.access_token;
    localStorage.setItem('nova_studio_token', authToken);
    await refreshCurrentUser();
    await refreshControlPlane();
    controlLog(`login ok: ${userId}`);
  } catch (err) {
    controlLog(`login failed: ${err.message}`);
  }
}

function studioLogout() {
  authToken = '';
  localStorage.removeItem('nova_studio_token');
  const current = document.getElementById('current-user');
  if (current) current.textContent = 'anonymous';
  controlLog('logged out');
}

// Periodic health check
setInterval(async () => {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    document.getElementById('blocks').textContent = d.safety?.blocks || 0;
    document.getElementById('queue').textContent = d.bus?.queue_depth || 0;
    document.getElementById('consumer-lag').textContent = d.eventbus?.lag || 0;
    document.getElementById('pending').textContent = d.eventbus?.pending || 0;
    document.getElementById('retries').textContent = d.eventbus?.retries || 0;
    document.getElementById('dlq').textContent = d.eventbus?.dlq_length || 0;
    document.getElementById('char-name').textContent = d.character || 'NOVA';
    const uptime = Math.floor((Date.now() - startTime) / 1000);
    const m = Math.floor(uptime / 60), s = uptime % 60;
    document.getElementById('uptime').textContent = `${m}m ${s}s`;
  } catch(e) {}
}, 5000);

setInterval(async () => {
  try {
    const d = await getJson('/studio/api/status');
    document.getElementById('runtime-role').textContent = d.runtime?.role || 'unknown';
    document.getElementById('runtime-instance').textContent = d.runtime?.instance_name || 'unknown';
    document.getElementById('runtime-session').textContent = d.runtime?.session_id || 'unknown';
    document.getElementById('runtime-hot').textContent = String(d.runtime?.hot_state || false);
    document.getElementById('conv-count').textContent = d.history?.conversation_count || 0;
    document.getElementById('safety-count').textContent = d.history?.safety_count || 0;

    const preview = document.getElementById('history-preview');
    preview.innerHTML = '';
    const items = d.history_preview || [];
    items.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'event-row';
      row.textContent = `${item.kind}: ${item.text}`;
      preview.appendChild(row);
    });
  } catch(e) {}
}, 5000);

setInterval(refreshControlPlane, 10000);
refreshCurrentUser();
refreshControlPlane();
loadConfigForm();
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def studio_dashboard():
    """Serve the Nova Studio dashboard."""
    return HTMLResponse(STUDIO_HTML)


@router.get("/api/status")
async def studio_status(request: Request):
    """Get current system status for Studio."""
    nova = request.app.state.nova
    hot_summary = {}
    history = {"conversation_count": 0, "safety_count": 0}
    if getattr(nova, "hot_session", None):
        hot_summary = await nova.hot_session.get_session() or {}
    bus_stats = nova.bus.stats() if getattr(nova, "bus", None) else {}
    if getattr(nova, "postgres_store", None):
        conversations = await nova.postgres_store.list_conversation_turns(limit=20)
        safety = await nova.postgres_store.list_safety_events(limit=20)
        history["conversation_count"] = len(conversations)
        history["safety_count"] = len(safety)
        history_preview = (
            [{"kind": "conversation", "text": item.get("text_content", "")[:80]} for item in conversations[:5]]
            + [{"kind": "safety", "text": item.get("category", "")[:80]} for item in safety[:5]]
        )[:8]
    else:
        history_preview = []
    current_user = getattr(request.state, "user", None)
    return JSONResponse({
        "status": "ok",
        "character": nova.personality.character_name if nova.personality else "NOVA",
        "auth": {
            "enabled": nova.settings.auth.enabled,
            "current_user": current_user,
        },
        "runtime": {
            "role": nova.settings.runtime.role,
            "instance_name": nova.settings.runtime.instance_name,
            "session_id": nova.settings.runtime.session_id,
            "hot_state": nova.hot_state is not None,
        },
        "bus": bus_stats,
        "summary": hot_summary,
        "history": history,
        "history_preview": history_preview,
    })
