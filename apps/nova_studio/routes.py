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
  :root {
    --bg-0: #07111f;
    --bg-1: #0d1728;
    --bg-2: #101c30;
    --panel: rgba(13, 23, 40, 0.86);
    --panel-strong: rgba(16, 28, 48, 0.94);
    --line: rgba(255,255,255,0.08);
    --line-strong: rgba(125, 211, 252, 0.18);
    --text-0: #edf4ff;
    --text-1: #b8c6dc;
    --text-2: #7f92ae;
    --accent: #6ee7f9;
    --accent-2: #38bdf8;
    --ok: #34d399;
    --warn: #f59e0b;
    --err: #fb7185;
    --shadow: 0 22px 60px rgba(2, 8, 20, 0.42);
  }
  body {
    background:
      radial-gradient(circle at top left, rgba(56, 189, 248, 0.14), transparent 26%),
      radial-gradient(circle at top right, rgba(14, 165, 233, 0.10), transparent 22%),
      linear-gradient(180deg, var(--bg-0) 0%, var(--bg-1) 40%, var(--bg-2) 100%);
    color: var(--text-0);
    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
    letter-spacing: 0.01em;
  }
  .card {
    background: linear-gradient(180deg, rgba(18, 30, 50, 0.92), rgba(12, 21, 37, 0.96));
    border: 1px solid var(--line);
    border-radius: 16px;
    box-shadow: var(--shadow);
    backdrop-filter: blur(18px);
  }
  .card:hover { border-color: var(--line-strong); }
  .pulse { animation: pulse 2s ease-in-out infinite; }
  @keyframes pulse { 0%,100% { opacity: 0.6; } 50% { opacity: 1; } }
  .event-row {
    border-bottom: 1px solid rgba(255,255,255,0.05);
    padding: 8px 10px;
    font-size: 12px;
    border-radius: 10px;
  }
  .event-row:hover { background: rgba(255,255,255,0.03); }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 10px; margin-right: 4px; }
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
  .workspace-sidebar {
    background: linear-gradient(180deg, rgba(8, 16, 29, 0.95), rgba(11, 18, 31, 0.92));
    border-right: 1px solid rgba(255,255,255,0.06);
  }
  .workspace-sidebar a {
    color: var(--text-1) !important;
    border-radius: 12px;
    padding: 8px 10px !important;
    transition: background 160ms ease, color 160ms ease, transform 160ms ease;
  }
  .workspace-sidebar a:hover {
    color: var(--text-0) !important;
    background: rgba(255,255,255,0.05) !important;
    transform: translateX(2px);
  }
  .workspace-header {
    background: rgba(8, 16, 29, 0.52);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 16px;
    padding: 10px 14px;
    backdrop-filter: blur(14px);
  }
  input, textarea, select {
    background: rgba(5, 10, 18, 0.42) !important;
    border-color: rgba(255,255,255,0.08) !important;
    color: var(--text-0) !important;
    border-radius: 12px !important;
  }
  input::placeholder, textarea::placeholder { color: var(--text-2); }
  button {
    border-radius: 12px !important;
    transition: transform 140ms ease, opacity 140ms ease;
  }
  button:hover { transform: translateY(-1px); }
  .section-kicker {
    color: var(--text-2);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
  }
  .section-copy { color: var(--text-1); font-size: 12px; line-height: 1.55; }
  .stat-card {
    position: relative;
    overflow: hidden;
  }
  .stat-card::after {
    content: "";
    position: absolute;
    inset: 0 auto 0 0;
    width: 3px;
    background: linear-gradient(180deg, var(--accent), transparent);
    opacity: 0.9;
  }
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 11px;
    background: rgba(255,255,255,0.06);
    color: var(--text-1);
  }
  .pill-ok { color: #d1fae5; background: rgba(16, 185, 129, 0.18); }
  .pill-warn { color: #fef3c7; background: rgba(245, 158, 11, 0.18); }
  .pill-err { color: #ffe4e6; background: rgba(244, 63, 94, 0.18); }
  .json-view {
    white-space: pre-wrap;
    word-break: break-word;
    font-family: "Cascadia Code", "SF Mono", monospace;
    font-size: 12px;
    color: var(--text-1);
    line-height: 1.55;
  }
  .list-card {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 12px;
    border-bottom: 1px solid rgba(255,255,255,0.05);
    border-radius: 12px;
  }
  .list-card:hover { background: rgba(255,255,255,0.035); }
  .list-title { font-size: 12px; color: var(--text-0); font-weight: 600; }
  .list-meta { font-size: 11px; color: var(--text-2); margin-top: 4px; line-height: 1.45; }
  .muted-note { color: var(--text-2); font-size: 11px; line-height: 1.55; }
</style>
</head>
<body class="min-h-screen">
<div class="studio-shell flex h-screen">
  <!-- Sidebar -->
  <div class="workspace-sidebar w-52 p-4 flex flex-col gap-2">
    <div class="text-sm font-bold mb-4 text-white/80">NOVA Studio</div>
    <a href="#" onclick="showTab('dashboard')" class="text-xs text-white/60 hover:text-white/90 px-2 py-1 rounded hover:bg-white/5">Dashboard</a>
    <a href="#" onclick="showTab('guide')" class="text-xs text-white/60 hover:text-white/90 px-2 py-1 rounded hover:bg-white/5">Guide</a>
    <a href="#" onclick="showTab('events')" class="text-xs text-white/60 hover:text-white/90 px-2 py-1 rounded hover:bg-white/5">Events</a>
    <a href="#" onclick="showTab('config')" class="text-xs text-white/60 hover:text-white/90 px-2 py-1 rounded hover:bg-white/5">Config</a>
    <a href="#" onclick="showTab('control')" class="text-xs text-white/60 hover:text-white/90 px-2 py-1 rounded hover:bg-white/5">Control</a>
    <a href="#" onclick="showTab('platforms')" class="text-xs text-white/60 hover:text-white/90 px-2 py-1 rounded hover:bg-white/5">Platforms</a>
    <div class="mt-auto text-[10px] text-white/30">v1.0.0</div>
  </div>

  <!-- Main -->
  <div class="flex-1 overflow-auto p-6">
    <!-- Header -->
    <div class="workspace-header flex items-center gap-3 mb-6">
      <span id="status-dot" class="dot-ok"></span>
      <div>
        <div class="text-sm font-semibold" id="char-name">NOVA</div>
        <div class="text-[11px] text-white/45">Enterprise runtime console</div>
      </div>
      <div class="ml-auto flex items-center gap-3">
        <input id="login-user-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="user id">
        <button onclick="studioLogin()" class="bg-blue-500/20 hover:bg-blue-500/30 text-blue-200 rounded px-2 py-1 text-xs">Login</button>
        <button onclick="studioLogout()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Logout</button>
        <div class="pill" id="current-user-pill">
          <span class="text-[10px] uppercase tracking-[0.16em] text-white/35">Session</span>
          <span class="text-xs text-white/70" id="current-user">anonymous</span>
        </div>
      </div>
      <span class="text-xs text-white/40" id="uptime">—</span>
    </div>

    <!-- Dashboard Tab -->
    <div id="tab-dashboard">
      <div class="grid grid-cols-2 gap-4 mb-6">
        <div class="card p-4">
          <div class="section-kicker mb-3">Quick Start</div>
          <div class="text-xs text-white/50 mb-3">Follow the 1.0 delivery path in order so each required action is obvious from the first screen.</div>
          <div id="startup-checklist" class="space-y-2 text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="section-kicker mb-3">Quick Actions</div>
          <div class="grid grid-cols-2 gap-2">
            <button onclick="showTab('config'); loadConfigForm()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-2 text-xs">Open Config Center</button>
            <button onclick="showTab('control'); refreshControlPlane()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-2 text-xs">Refresh Control Plane</button>
            <button onclick="reloadCharacterConfig()" class="bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-200 rounded px-2 py-2 text-xs">Reload Character Card</button>
            <button onclick="showTab('events')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-2 text-xs">Open Event Stream</button>
            <button onclick="refreshCurrentUser()" class="bg-blue-500/20 hover:bg-blue-500/30 text-blue-200 rounded px-2 py-2 text-xs">Refresh Current User</button>
            <button onclick="loadConfigForm()" class="bg-green-500/20 hover:bg-green-500/30 text-green-200 rounded px-2 py-2 text-xs">Reload Saved Config</button>
          </div>
          <div id="dashboard-banner" class="mt-3 text-xs text-white/50">Sign in first, then finish Config and Control setup before running acceptance checks.</div>
        </div>
      </div>

      <div class="card p-4 mb-6" id="overview-center">
        <div class="section-kicker mb-3">Center Map</div>
        <div class="section-copy mb-4">Use the overview as the command surface for the nine operating centers that make up NOVA 1.0 delivery.</div>
        <div class="grid grid-cols-3 gap-3">
          <button onclick="showTab('dashboard'); scrollIntoViewId('overview-center')" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-3 text-left text-xs">Overview Center<br><span class='text-white/50'>Overview, readiness, quick actions</span></button>
          <button onclick="showTab('dashboard'); scrollIntoViewId('runtime-center')" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-3 text-left text-xs">Runtime Center<br><span class='text-white/50'>Workers, issues, hot state, event flow</span></button>
          <button onclick="showTab('control'); scrollIntoViewId('control-center')" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-3 text-left text-xs">Control Center<br><span class='text-white/50'>Tenants, users, roles, revisions</span></button>
          <button onclick="showTab('config'); scrollIntoViewId('config-center')" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-3 text-left text-xs">Config Center<br><span class='text-white/50'>Providers, toggles, output strategy</span></button>
          <button onclick="showTab('control'); scrollIntoViewId('role-center')" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-3 text-left text-xs">Role Center<br><span class='text-white/50'>Roles, permissions, bindings</span></button>
          <button onclick="showTab('platforms'); scrollIntoViewId('platform-center')" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-3 text-left text-xs">Platform Center<br><span class='text-white/50'>Catalog, templates, runtime status</span></button>
          <button onclick="showTab('control'); scrollIntoViewId('audit-center')" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-3 text-left text-xs">Audit Center<br><span class='text-white/50'>Audit explorer and evidence</span></button>
          <button onclick="showTab('dashboard'); scrollIntoViewId('diagnostics-center')" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-3 text-left text-xs">Diagnostics Center<br><span class='text-white/50'>Diagnostics, metrics, runtime issues</span></button>
          <button onclick="showTab('guide'); scrollIntoViewId('acceptance-center')" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-3 text-left text-xs">Acceptance Center<br><span class='text-white/50'>Checks, walkthroughs, delivery proof</span></button>
        </div>
      </div>

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

      <div class="grid grid-cols-2 gap-4 mb-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Open Platform Readiness</div>
          <div class="space-y-2 text-xs text-white/70">
            <div class="event-row">Platform catalog, templates, status and debug lanes are now exposed in the dedicated Platforms workbench.</div>
            <div class="event-row">Use the Platforms tab to inspect adapter metadata, load templates, validate config and inject normalized debug events.</div>
            <div class="event-row">This dashboard stays focused on runtime posture, customer readiness and delivery shortcuts.</div>
          </div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Workspace Lanes</div>
          <div class="grid grid-cols-2 gap-2">
            <button onclick="showTab('config'); loadConfigForm()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs text-left">Configuration Center</button>
            <button onclick="showTab('control'); refreshControlPlane()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs text-left">Control Plane</button>
            <button onclick="showTab('platforms')" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-3 py-2 text-xs text-left">Open Platform Console</button>
            <button onclick="showTab('guide'); runAcceptanceChecks()" class="bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 rounded px-3 py-2 text-xs text-left">Acceptance Mode</button>
          </div>
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

      <div class="grid grid-cols-2 gap-4 mt-4" id="diagnostics-center">
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

      <div class="grid grid-cols-2 gap-4 mt-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Current User Context</div>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div class="event-row"><span class="text-white/45">User</span><div class="list-title mt-1" id="dash-auth-user">anonymous</div></div>
            <div class="event-row"><span class="text-white/45">Tenant Scope</span><div class="list-title mt-1" id="dash-auth-tenant">n/a</div></div>
            <div class="event-row"><span class="text-white/45">Roles</span><div class="list-title mt-1" id="dash-auth-roles">none</div></div>
            <div class="event-row"><span class="text-white/45">Permission Count</span><div class="list-title mt-1" id="dash-auth-permission-count">0</div></div>
          </div>
          <div class="muted-note mt-3">The signed-in identity directly changes what the Control center can see and modify.</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Environment Readiness</div>
          <div id="environment-summary" class="space-y-2 text-xs text-white/70"></div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4 mt-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Runtime Issues</div>
          <div id="runtime-issues" class="max-h-[220px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Hot State Summary</div>
          <div id="hot-state-summary" class="max-h-[220px] overflow-auto text-xs text-white/70"></div>
        </div>
      </div>

      <div class="card p-4 mt-4" id="runtime-center">
        <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Runtime Explorer</div>
        <div class="grid grid-cols-3 gap-2 mb-3">
          <button onclick="loadRuntimeExplorer('overview')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-2 text-xs">Overview</button>
          <button onclick="loadRuntimeExplorer('hot_state')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-2 text-xs">Hot State</button>
          <button onclick="loadRuntimeExplorer('sessions')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-2 text-xs">Sessions</button>
          <button onclick="loadRuntimeExplorer('viewers')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-2 text-xs">Viewers</button>
          <button onclick="loadRuntimeExplorer('history')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-2 text-xs">History</button>
          <button onclick="loadRuntimeExplorer('audit')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-2 text-xs">Audit</button>
        </div>
        <div id="runtime-explorer-detail" class="max-h-[220px] overflow-auto text-xs text-white/70"></div>
      </div>

      <div class="grid grid-cols-2 gap-4 mt-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Runtime Workers</div>
          <div id="worker-status" class="max-h-[220px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Event Injection</div>
          <div class="grid grid-cols-2 gap-2 mb-3">
            <input id="inject-event-type" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="event type e.g. CHAT_MESSAGE">
            <input id="inject-priority" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="priority NORMAL/HIGH">
            <input id="inject-viewer-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="viewer id">
            <input id="inject-username" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="username">
            <textarea id="inject-text" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs col-span-2 h-20" placeholder="event text"></textarea>
          </div>
          <div class="grid grid-cols-3 gap-2 mb-3">
            <button onclick="applyInjectPreset('chat')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Chat Preset</button>
            <button onclick="applyInjectPreset('gift')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Gift Preset</button>
            <button onclick="applyInjectPreset('follow')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Follow Preset</button>
          </div>
          <div class="flex gap-2">
            <button onclick="injectRuntimeEvent()" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-3 py-2 text-xs">Inject Event</button>
            <button onclick="runRuntimeSmoke()" class="bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 rounded px-3 py-2 text-xs">Run Smoke Chain</button>
            <button onclick="loadDiagnostics()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Refresh Diagnostics</button>
          </div>
          <div class="text-xs text-white/40 mt-3" id="inject-status">Use this to verify perception → cognitive → generation without a real platform feed.</div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4 mt-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Diagnostics Snapshot</div>
          <div id="runtime-diagnostics-detail" class="max-h-[220px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Metrics Snapshot</div>
          <div id="runtime-metrics-detail" class="max-h-[220px] overflow-auto text-xs text-white/70"></div>
        </div>
      </div>
    </div>

    <!-- Platforms Tab -->
    <div id="tab-platforms" style="display:none">
      <div id="platform-center"></div>
      <div class="grid grid-cols-4 gap-4 mb-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">Catalog</div>
          <div id="platform-summary-catalog" class="text-2xl font-semibold text-white">0</div>
          <div class="text-xs text-white/50 mt-1">registered platform specs</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">Configured</div>
          <div id="platform-summary-configured" class="text-2xl font-semibold text-cyan-200">0</div>
          <div class="text-xs text-white/50 mt-1">saved platform configs</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">Healthy</div>
          <div id="platform-summary-healthy" class="text-2xl font-semibold text-emerald-200">0</div>
          <div class="text-xs text-white/50 mt-1">runtime healthy adapters</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">Issues</div>
          <div id="platform-summary-issues" class="text-2xl font-semibold text-amber-200">0</div>
          <div class="text-xs text-white/50 mt-1">validation or runtime problems</div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4 mb-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Platform Catalog</div>
          <div class="flex gap-2 mb-3">
            <button onclick="loadPlatformCatalog()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Load Catalog</button>
            <button onclick="loadPlatformTemplates()" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-3 py-2 text-xs">Load Templates</button>
          </div>
          <div class="grid grid-cols-2 gap-2 mb-3">
            <select id="platform-template-select" class="bg-black/20 border border-white/10 rounded px-2 py-2 text-xs text-white/70"></select>
            <button onclick="applySelectedPlatformTemplate()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Apply Template</button>
          </div>
          <div id="platform-catalog" class="max-h-[260px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Platform Runtime Status</div>
          <div class="flex gap-2 mb-3">
            <button onclick="loadPlatformStatus()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Refresh Status</button>
            <button onclick="reloadPlatformRuntime()" class="bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 rounded px-3 py-2 text-xs">Reload Platforms</button>
          </div>
          <div id="platform-status" class="max-h-[260px] overflow-auto text-xs text-white/70"></div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4 mb-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Platform Detail</div>
          <div class="flex gap-2 mb-3">
            <input id="platform-detail-input" class="bg-black/20 border border-white/10 rounded px-2 py-2 text-xs text-white/70 flex-1" placeholder="platform id e.g. bilibili">
            <button onclick="loadPlatformDetail()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Inspect</button>
          </div>
          <div id="platform-detail" class="max-h-[260px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Extension Entry Spec</div>
          <div class="flex gap-2 mb-3">
            <button onclick="loadPlatformExtensionSpec()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Load Spec</button>
          </div>
          <div id="platform-extension-spec" class="max-h-[260px] overflow-auto text-xs text-white/70"></div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4 mb-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Template Library</div>
          <div class="grid grid-cols-2 gap-2 mb-3">
            <select id="library-kind-select" onchange="updateLibraryItemOptions()" class="bg-black/20 border border-white/10 rounded px-2 py-2 text-xs text-white/70"></select>
            <select id="library-item-select" class="bg-black/20 border border-white/10 rounded px-2 py-2 text-xs text-white/70"></select>
          </div>
          <div class="flex gap-2 mb-3">
            <button onclick="loadLibraryCatalog()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Reload Library</button>
            <button onclick="loadLibraryTemplateDetail()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Preview</button>
            <button onclick="applyLibraryTemplate()" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-3 py-2 text-xs">Apply</button>
          </div>
          <div id="library-preview" class="max-h-[260px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Extension Docs</div>
          <div class="grid grid-cols-2 gap-2 mb-3">
            <select id="extension-doc-select" class="bg-black/20 border border-white/10 rounded px-2 py-2 text-xs text-white/70"></select>
            <button onclick="loadExtensionDocDetail()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Open Doc</button>
          </div>
          <div id="extension-doc-preview" class="max-h-[260px] overflow-auto text-xs text-white/70"></div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Platform Config Editor</div>
          <div class="grid grid-cols-2 gap-2 mb-3">
            <input id="platform-config-filter" class="bg-black/20 border border-white/10 rounded px-2 py-2 text-xs text-white/70" placeholder="optional platform filter">
            <button onclick="loadPlatformConfig()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Load Config</button>
          </div>
          <div class="text-xs text-white/50 mb-3">Use one JSON object per line. Start from a template, adapt it for the selected platform, validate it, then save.</div>
          <textarea id="platform-config-editor" class="w-full h-[360px] bg-black/20 border border-white/10 rounded px-2 py-2 text-xs text-white/70 mb-3"></textarea>
          <div class="flex gap-2">
            <button onclick="validatePlatformConfig()" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-3 py-2 text-xs">Validate</button>
            <button onclick="savePlatformConfig()" class="bg-green-500/20 hover:bg-green-500/30 text-green-200 rounded px-3 py-2 text-xs">Save</button>
          </div>
          <div id="platform-config-status" class="text-xs text-white/40 mt-3">Saved platform config still needs Reload Platforms or a process restart before adapters consume it.</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Platform Event Debug</div>
          <div class="grid grid-cols-2 gap-2 mb-3">
            <input id="platform-debug-name" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="platform e.g. bilibili">
            <input id="platform-debug-event-type" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="event type e.g. CHAT_MESSAGE">
            <input id="platform-debug-priority" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="priority NORMAL/HIGH">
            <input id="platform-debug-trace-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="trace id (optional)">
            <input id="platform-debug-viewer-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="viewer id">
            <input id="platform-debug-username" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="username">
            <textarea id="platform-debug-text" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs col-span-2 h-20" placeholder="message text"></textarea>
            <textarea id="platform-debug-payload" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs col-span-2 h-28" placeholder="optional raw payload JSON"></textarea>
          </div>
          <div class="grid grid-cols-3 gap-2 mb-3">
            <button onclick="applyPlatformDebugPreset('bilibili')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Bilibili</button>
            <button onclick="applyPlatformDebugPreset('douyin')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Douyin</button>
            <button onclick="applyPlatformDebugPreset('youtube')" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">YouTube</button>
          </div>
          <div class="flex gap-2">
            <button onclick="sendPlatformTestEvent()" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-3 py-2 text-xs">Send Test Event</button>
            <button onclick="showTab('events')" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Watch Event Stream</button>
          </div>
          <div id="platform-debug-status" class="text-xs text-white/40 mt-3">Use platform test events to validate adapter normalization without touching downstream code.</div>
        </div>
      </div>
    </div>

    <!-- Guide Tab -->
    <div id="tab-guide" style="display:none">
      <div class="grid grid-cols-2 gap-4 mb-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Initialization Wizard</div>
          <div class="text-xs text-white/50 mb-3">Complete tenants, roles, permissions, users, and revisions in the recommended 1.0 order.</div>
          <div id="wizard-init-steps" class="space-y-2 text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Configuration Wizard</div>
          <div class="text-xs text-white/50 mb-3">Apply a runtime preset first, then fine-tune the result in the Config center.</div>
          <div class="grid grid-cols-1 gap-2">
            <button onclick="applyConfigPreset('local')" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs text-left">Local Preview Preset</button>
            <button onclick="applyConfigPreset('control')" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-3 py-2 text-xs text-left">Control Plane Preset</button>
            <button onclick="applyConfigPreset('acceptance')" class="bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-200 rounded px-3 py-2 text-xs text-left">Acceptance Preset</button>
          </div>
          <div class="text-xs text-white/40 mt-3">Presets fill only the core fields. Review and save them yourself.</div>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-4 mt-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">AI Eval Latest Report</div>
          <div class="flex gap-2 mb-3">
            <button onclick="loadAiEvalReport()" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Load AI Eval</button>
            <button onclick="previewRouting()" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-3 py-2 text-xs">Routing Preview</button>
          </div>
          <textarea id="ai-routing-input" class="w-full h-16 bg-black/20 border border-white/10 rounded px-2 py-2 text-xs text-white/70 mb-2" placeholder="Type one message to preview NLU and routing behavior."></textarea>
          <input id="ai-routing-emotion" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs w-full mb-3" placeholder="emotion: neutral/excited/sad/calm/curious">
          <div id="ai-eval-summary" class="max-h-[240px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">AI Eval Detail</div>
          <div id="ai-eval-detail" class="max-h-[320px] overflow-auto text-xs text-white/70"></div>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-4">
        <div class="card p-4" id="acceptance-center">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Acceptance Mode</div>
          <div class="text-xs text-white/50 mb-3">Run the final 1.0 acceptance path against the current workstation and environment.</div>
          <div class="flex gap-2 mb-3">
            <button onclick="runAcceptanceChecks()" class="bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 rounded px-3 py-2 text-xs">Run Acceptance Checks</button>
            <button onclick="openDiagnosticsCenter()" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-3 py-2 text-xs">One-click Diagnose</button>
            <button onclick="exportAcceptanceReport()" class="bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-200 rounded px-3 py-2 text-xs">Export Acceptance</button>
            <button onclick="showTab('dashboard')" class="bg-white/10 hover:bg-white/20 text-white rounded px-3 py-2 text-xs">Back to Dashboard</button>
          </div>
          <div id="acceptance-checks" class="space-y-2 text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Wizard Feedback</div>
          <div class="text-xs text-white/50 mb-3">This area shows wizard actions, acceptance runs, and guided-navigation feedback in real time.</div>
          <div id="wizard-log" class="max-h-[320px] overflow-auto text-xs text-white/70"></div>
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
        <div class="card p-4" id="config-center">
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
                <input id="cfg-llm-provider" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="LLM provider">
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
                <input id="cfg-voice-fallback-chain" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="voice fallback chain: edge_tts,azure">
                <label class="text-xs text-white/70 flex items-center gap-2"><input type="checkbox" id="cfg-avatar-enabled"> Avatar Enabled</label>
                <input id="cfg-avatar-driver" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="avatar driver">
                <input id="cfg-output-strategy" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="output strategy">
              </div>
            </div>
            <div>
              <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">Knowledge & Persistence</div>
              <div class="flex flex-col gap-2">
                <label class="text-xs text-white/70 flex items-center gap-2"><input type="checkbox" id="cfg-knowledge-enabled"> RAG Enabled</label>
                <input id="cfg-knowledge-embedding-backend" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="embedding backend">
                <input id="cfg-knowledge-embedding-model" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="embedding model">
                <input id="cfg-knowledge-vector-backend" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="vector backend">
                <input id="cfg-knowledge-top-k" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="knowledge retrieval top_k">
                <input id="cfg-knowledge-score-threshold" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="knowledge score threshold">
                <input id="cfg-persistence-backend" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="persistence backend">
                <input id="cfg-postgres-url" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="postgres url">
                <input id="cfg-redis-url" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="redis url">
              </div>
            </div>
          </div>
          <div class="grid grid-cols-2 gap-3 mt-4">
            <div>
              <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">AI Routing</div>
              <div class="flex flex-col gap-2">
                <label class="text-xs text-white/70 flex items-center gap-2"><input type="checkbox" id="cfg-tools-enabled"> Tools Enabled</label>
                <input id="cfg-tools-max-rounds" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="tool max rounds">
                <input id="cfg-nlu-confidence-threshold" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="NLU confidence threshold">
              </div>
            </div>
            <div>
              <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">Memory Consolidation</div>
              <div class="flex flex-col gap-2">
                <label class="text-xs text-white/70 flex items-center gap-2"><input type="checkbox" id="cfg-memory-enabled"> Memory Enabled</label>
                <input id="cfg-memory-working-maxlen" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="working memory maxlen">
                <label class="text-xs text-white/70 flex items-center gap-2"><input type="checkbox" id="cfg-consolidation-enabled"> Consolidation Enabled</label>
                <label class="text-xs text-white/70 flex items-center gap-2"><input type="checkbox" id="cfg-consolidation-idle-only"> Idle Only</label>
                <input id="cfg-consolidation-interval-s" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="consolidation interval seconds">
                <input id="cfg-consolidation-min-entries" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="consolidation min entries">
                <input id="cfg-consolidation-min-idle-s" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="consolidation min idle seconds">
              </div>
            </div>
          </div>
          <div class="flex gap-2 mt-4">
            <button onclick="loadConfigForm()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Reload Settings</button>
            <button onclick="loadCapabilityCatalog()" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-2 py-1 text-xs">Load Capability Catalog</button>
            <button onclick="saveConfigForm()" class="bg-green-500/20 hover:bg-green-500/30 text-green-200 rounded px-2 py-1 text-xs">Save Config</button>
            <button onclick="reloadCharacterConfig()" class="bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-200 rounded px-2 py-1 text-xs">Reload Character</button>
          </div>
          <div class="text-xs text-white/40 mt-3" id="config-save-status">Settings are persisted to nova.config.json. Runtime restart is only required for structural changes.</div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Effective Config Summary</div>
          <div class="text-xs text-white/60 mb-3" id="config-display">Loading…</div>
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">Capability Catalog</div>
          <div id="capability-catalog-preview" class="max-h-[160px] overflow-auto text-xs text-white/70 mb-3"></div>
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-2">Advanced JSON Preview</div>
          <textarea id="config-json-preview" class="w-full h-[420px] bg-black/20 border border-white/10 rounded px-2 py-2 text-xs text-white/70"></textarea>
        </div>
      </div>
    </div>

    <!-- Control Tab -->
    <div id="tab-control" style="display:none">
      <div class="grid grid-cols-2 gap-4 mb-4">
        <div class="card p-4" id="control-center">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Workbench</div>
          <div class="grid grid-cols-3 gap-2 text-xs mb-3">
            <div class="event-row"><span class="text-white/45">User</span><div class="list-title mt-1" id="auth-user-id">anonymous</div></div>
            <div class="event-row"><span class="text-white/45">Tenant Scope</span><div class="list-title mt-1" id="auth-tenant-scope">n/a</div></div>
            <div class="event-row"><span class="text-white/45">Roles</span><div class="list-title mt-1" id="auth-role-list">none</div></div>
          </div>
          <div class="text-xs text-white/60 mt-2">Permissions</div>
          <div id="auth-permission-list" class="text-xs text-white/70 mt-1 max-h-[100px] overflow-auto"></div>
        </div>
        <div class="card p-4" id="role-center">
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
        <div class="card p-4" id="audit-center">
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
            <input id="revision-operator" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="operator / changed by">
            <input id="revision-note" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="change note / remark">
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
          <div class="flex gap-2 mb-2">
            <input id="tenant-filter-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs flex-1" placeholder="tenant id filter">
            <button onclick="refreshControlPlane()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Search</button>
          </div>
          <div id="tenant-list" class="max-h-[320px] overflow-auto text-xs text-white/70"></div>
          <div id="tenant-pagination" class="flex items-center justify-between mt-2 text-[11px] text-white/50"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Roles</div>
          <div class="flex gap-2 mb-2">
            <input id="role-filter-tenant-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs flex-1" placeholder="tenant id filter">
            <button onclick="refreshControlPlane()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Search</button>
          </div>
          <div id="role-list" class="max-h-[320px] overflow-auto text-xs text-white/70"></div>
          <div id="role-pagination" class="flex items-center justify-between mt-2 text-[11px] text-white/50"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Config Revisions</div>
          <div class="grid grid-cols-2 gap-2 mb-2">
            <input id="revision-filter-tenant-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="tenant id">
            <input id="revision-filter-resource-type" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="resource type">
            <input id="revision-filter-resource-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="resource id">
            <input id="revision-filter-status" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="status">
          </div>
          <div class="flex gap-2 mb-2">
            <button onclick="refreshControlPlane()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Search</button>
            <button onclick="loadEffectiveRevision()" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-2 py-1 text-xs">Effective</button>
          </div>
          <div id="revision-list" class="max-h-[320px] overflow-auto text-xs text-white/70"></div>
          <div id="revision-pagination" class="flex items-center justify-between mt-2 text-[11px] text-white/50"></div>
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
          <div id="permission-pagination" class="flex items-center justify-between mt-2 text-[11px] text-white/50"></div>
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
          <div class="flex gap-2 mb-2">
            <input id="user-filter-tenant-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs flex-1" placeholder="tenant id filter">
            <input id="user-filter-status" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs flex-1" placeholder="status">
          </div>
          <div class="flex gap-2 mb-2">
            <button onclick="refreshControlPlane()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Search</button>
          </div>
          <div id="user-list" class="max-h-[240px] overflow-auto text-xs text-white/70"></div>
          <div id="user-pagination" class="flex items-center justify-between mt-2 text-[11px] text-white/50"></div>
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
      <div class="grid grid-cols-2 gap-4 mt-4">
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Current Effective Revision</div>
          <div class="grid grid-cols-2 gap-2 mb-3">
            <input id="effective-tenant-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="tenant id">
            <input id="effective-resource-type" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="resource type">
            <input id="effective-resource-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs col-span-2" placeholder="resource id">
          </div>
          <button onclick="loadEffectiveRevision()" class="bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-200 rounded px-2 py-1 text-xs mb-3">Load Effective Revision</button>
          <div id="effective-revision-detail" class="max-h-[220px] overflow-auto text-xs text-white/70"></div>
        </div>
        <div class="card p-4">
          <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Audit Explorer</div>
          <div class="grid grid-cols-2 gap-2 mb-3">
            <input id="audit-filter-action" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="action">
            <input id="audit-filter-resource-type" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs" placeholder="resource type">
            <input id="audit-filter-resource-id" class="bg-black/20 border border-white/10 rounded px-2 py-1 text-xs col-span-2" placeholder="resource id">
          </div>
          <div class="flex gap-2 mb-3">
            <button onclick="loadAudit()" class="bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-xs">Search Audit</button>
          </div>
          <div id="audit-list" class="max-h-[220px] overflow-auto text-xs text-white/70"></div>
          <div id="audit-pagination" class="flex items-center justify-between mt-2 text-[11px] text-white/50"></div>
        </div>
      </div>
      <div class="card p-4 mt-4">
        <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Resource Detail</div>
        <div class="text-xs text-white/40 mb-2">Use Inspect in any list to open the current resource detail.</div>
        <div id="resource-detail" class="max-h-[220px] overflow-auto text-xs text-white/70"></div>
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
let lastStudioStatus = null;
let lastConfigState = null;
let lastHealthState = null;
let lastDiagnosticsState = null;
let lastPlatformCatalog = [];
let lastLibraryCatalog = null;
let lastAcceptanceResults = [];
const pageState = {
  tenants: {offset: 0, limit: 10},
  roles: {offset: 0, limit: 10},
  revisions: {offset: 0, limit: 10},
  permissions: {offset: 0, limit: 10},
  users: {offset: 0, limit: 10},
  audit: {offset: 0, limit: 10},
};

function showTab(name) {
  ['dashboard','guide','events','config','control','platforms'].forEach(t => {
    document.getElementById('tab-'+t).style.display = t===name ? '' : 'none';
  });
  if (name === 'platforms') {
    loadPlatformCatalog();
    loadPlatformStatus();
    loadPlatformExtensionSpec();
    loadLibraryCatalog();
    loadExtensionDocCatalog();
  }
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

function wizardLog(message) {
  const log = document.getElementById('wizard-log');
  if (!log) return;
  const row = document.createElement('div');
  row.className = 'event-row';
  row.textContent = `${new Date().toLocaleTimeString()} ${message}`;
  log.prepend(row);
  while (log.children.length > 50) log.lastChild.remove();
}

function queryString(params) {
  const q = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      q.set(key, String(value).trim());
    }
  });
  const raw = q.toString();
  return raw ? `?${raw}` : '';
}

function setDashboardBanner(message, tone='neutral') {
  const node = document.getElementById('dashboard-banner');
  node.textContent = message;
  node.className = 'mt-3 text-xs ' + (
    tone === 'error' ? 'text-red-300' :
    tone === 'warn' ? 'text-amber-300' :
    tone === 'ok' ? 'text-emerald-300' :
    'text-white/50'
  );
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
    `Port: ${config.port Open '8765'}`,
    `Role: ${config.runtime?.role || 'all'}`,
    `Auth: ${config.auth?.enabled ? 'enabled' : 'disabled'}`,
    `LLM: ${config.llm?.provider || 'n/a'} / ${config.llm?.model || 'n/a'}`,
    `Character: ${config.character?.path || 'n/a'}`,
    `Voice: ${config.voice?.backend || 'n/a'} / ${config.voice?.voice_id || 'n/a'}`,
    `Output: ${config.avatar?.output_strategy || 'voice_only'}`,
    `RAG: ${config.knowledge?.enabled ? 'enabled' : 'disabled'}`,
    `Memory: ${config.memory?.enabled === false ? 'disabled' : 'enabled'}`,
    `Persistence: ${config.persistence?.backend || 'n/a'}`,
  ].join(' | ');
}

function renderStartupChecklist() {
  const target = document.getElementById('startup-checklist');
  if (!target) return;
  const authUser = document.getElementById('dash-auth-user')?.textContent || 'anonymous';
  const configReady = !!lastConfigState?.config_path;
  const runtimeReady = !!lastHealthState?.status;
  const controlReady = !!document.getElementById('tenant-list')?.children?.length;
  const steps = [
    {label: '1. Service started and workspace reachable', done: runtimeReady, action: "showTab('dashboard')"},
    {label: '2. Sign in with a valid Studio user', done: authUser !== 'anonymous', action: ''},
    {label: '3. Review and save the active runtime configuration', done: configReady, action: "showTab('config'); loadConfigForm()"},
    {label: '4. Create tenants, users, roles, and permissions', done: controlReady, action: "showTab('control'); refreshControlPlane()"},
    {label: '5. Publish a revision and verify event and history flow', done: !!lastStudioStatus?.history, action: "showTab('control')"},
  ];
  target.innerHTML = '';
  steps.forEach((step) => {
    const row = document.createElement('div');
    row.className = 'flex items-center justify-between gap-3 bg-black/10 rounded px-3 py-2';
    row.innerHTML = `<div><span class="${step.done ? 'text-emerald-300' : 'text-amber-300'}">${step.done ? '●' : '○'}</span> ${step.label}</div>`;
    if (step.action) {
      const button = document.createElement('button');
      button.className = 'bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-[11px]';
      button.textContent = 'Open';
      button.setAttribute('onclick', step.action);
      row.appendChild(button);
    }
    target.appendChild(row);
  });
}

function renderEnvironmentSummary() {
  const target = document.getElementById('environment-summary');
  if (!target) return;
  const status = lastStudioStatus || {};
  const config = lastConfigState || {};
  const authEnabled = config.runtime?.auth_enabled Open status.auth?.enabled Open false;
  const hotState = status.runtime?.hot_state Open false;
  const workerCount = Object.keys(lastDiagnosticsState?.workers?.platforms || {}).length;
  const items = [
    `Config File: ${config.config_path || 'not loaded'}`,
    `Auth: ${authEnabled ? 'enabled' : 'disabled'}`,
    `Hot State: ${hotState ? 'enabled' : 'disabled'}`,
    `History: ${(status.history?.conversation_count || 0)} convo / ${(status.history?.safety_count || 0)} safety`,
    `Bus Pending/Lag: ${(status.bus?.pending || 0)} / ${(status.bus?.consumer_lag || status.bus?.lag || 0)}`,
    `Platform Workers: ${workerCount}`,
  ];
  target.innerHTML = '';
  items.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'event-row';
    row.textContent = item;
    target.appendChild(row);
  });
}

function renderEmptyState(elementId, title, detail='No data available yet.') {
  const target = document.getElementById(elementId);
  if (!target) return;
  target.innerHTML = '';
  const box = document.createElement('div');
  box.className = 'event-row text-white/60';
  box.innerHTML = `<div class="font-semibold text-white/80">${title}</div><div class="mt-1 text-white/45">${detail}</div>`;
  target.appendChild(box);
}

function renderErrorState(elementId, title, detail) {
  const target = document.getElementById(elementId);
  if (!target) return;
  target.innerHTML = '';
  const box = document.createElement('div');
  box.className = 'event-row text-rose-200';
  box.innerHTML = `<div class="font-semibold">${title}</div><div class="mt-1 text-rose-100/80">${detail}</div>`;
  target.appendChild(box);
}

function renderIssues(issues) {
  const target = document.getElementById('runtime-issues');
  if (!target) return;
  target.innerHTML = '';
  const list = issues || [];
  if (!list.length) {
    const row = document.createElement('div');
    row.className = 'list-card';
    row.innerHTML = `<div class="flex-1"><div class="list-title">No runtime issues detected</div><div class="list-meta">This runtime currently looks healthy enough for operator-facing work.</div></div><span class="pill pill-ok">OK</span>`;
    target.appendChild(row);
    return;
  }
  list.forEach((issue) => {
    const row = document.createElement('div');
    row.className = 'list-card';
    let hint = '';
    if (issue.code === 'eventbus_lag') hint = 'Action: inspect workers / inject fewer events / check model latency.';
    if (issue.code === 'eventbus_pending') hint = 'Action: inspect queue depth and retry counts.';
    if (issue.code === 'eventbus_dlq') hint = 'Action: review dead-letter queue and replay after fix.';
    if (String(issue.code || '').includes('platform_')) hint = 'Action: verify platform config and adapter health.';
    if (issue.code === 'orchestrator_down') hint = 'Action: check cognitive worker bootstrap and model connectivity.';
    if (issue.code === 'voice_down') hint = 'Action: verify generation worker and TTS backend.';
    row.innerHTML = `<div class="flex-1"><div class="list-title">${issue.code}</div><div class="list-meta">${issue.message}</div><div class="list-meta">${hint || 'No operator action required.'}</div></div><span class="pill ${issue.severity === 'critical' ? 'pill-err' : issue.severity === 'warning' ? 'pill-warn' : 'pill-ok'}">${(issue.severity || 'info').toUpperCase()}</span>`;
    target.appendChild(row);
  });
}

function renderHotStateSummary(summary) {
  const target = document.getElementById('hot-state-summary');
  if (!target) return;
  target.innerHTML = '';
  const payload = summary || {};
  const rows = [
    `session_id: ${payload.session_id || 'n/a'}`,
    `status: ${payload.status || 'n/a'}`,
    `chat_count: ${payload.chat_count Open 'n/a'}`,
    `gift_count: ${payload.gift_count Open 'n/a'}`,
    `follow_count: ${payload.follow_count Open 'n/a'}`,
    `last_output: ${payload.last_output || 'n/a'}`,
  ];
  rows.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'list-card';
    row.innerHTML = `<div class="list-meta">${item}</div>`;
    target.appendChild(row);
  });
}

function renderWorkerStatus(workers) {
  const target = document.getElementById('worker-status');
  if (!target) return;
  target.innerHTML = '';
  const sections = [
    ['API', workers?.api ? 'up' : 'down', `role gateway=${workers?.api ? 'ready' : 'down'}`],
    ['Perception', workers?.perception?.aggregator ? 'up' : 'down', `aggregator=${workers?.perception?.aggregator} | silence=${workers?.perception?.silence_detector} | context=${workers?.perception?.context_sensor}`],
    ['Cognitive', workers?.cognitive?.orchestrator ? 'up' : 'down', `memory=${workers?.cognitive?.memory} | emotion=${workers?.cognitive?.emotion} | personality=${workers?.cognitive?.personality} | nlu=${workers?.cognitive?.nlu} | orchestrator=${workers?.cognitive?.orchestrator}`],
    ['Generation', workers?.generation?.voice ? 'up' : 'down', `voice=${workers?.generation?.voice} | lipsync=${workers?.generation?.lipsync} | avatar=${workers?.generation?.avatar}`],
  ];
  sections.forEach(([label, health, meta]) => {
    const row = document.createElement('div');
    row.className = 'list-card';
    row.innerHTML = `<div class="flex-1"><div class="list-title">${label}</div><div class="list-meta">${meta}</div></div>
      <span class="pill ${health === 'up' ? 'pill-ok' : 'pill-err'}">${health}</span>`;
    target.appendChild(row);
  });
  const platforms = workers?.platforms || {};
  if (!Object.keys(platforms).length) {
    const row = document.createElement('div');
    row.className = 'list-card';
    row.innerHTML = `<div class="flex-1"><div class="list-title">No platform adapters are running</div><div class="list-meta">Apply a platform template and reload runtime to bring an adapter online.</div></div><span class="pill pill-warn">IDLE</span>`;
    target.appendChild(row);
  }
  Object.entries(platforms).forEach(([name, state]) => {
    const row = document.createElement('div');
    const health = state.health || 'unknown';
    row.className = 'list-card';
    row.innerHTML = `<div class="flex-1"><div class="list-title">Platform ${name}</div><div class="list-meta">running=${state.running} | events=${state.events_received} | errors=${state.errors} | last_event_ago_s=${state.last_event_ago_s Open 'n/a'}</div></div>
      <span class="pill ${health === 'healthy' ? 'pill-ok' : health === 'down' ? 'pill-err' : 'pill-warn'}">${health}</span>`;
    target.appendChild(row);
  });
}

function applyInjectPreset(mode) {
  if (mode === 'chat') {
    document.getElementById('inject-event-type').value = 'CHAT_MESSAGE';
    document.getElementById('inject-priority').value = 'NORMAL';
    document.getElementById('inject-viewer-id').value = 'demo-viewer';
    document.getElementById('inject-username').value = 'DemoViewer';
    document.getElementById('inject-text').value = 'Hello NOVA, run a runtime verification.';
  } else if (mode === 'gift') {
    document.getElementById('inject-event-type').value = 'GIFT_RECEIVED';
    document.getElementById('inject-priority').value = 'HIGH';
    document.getElementById('inject-viewer-id').value = 'gift-user';
    document.getElementById('inject-username').value = 'GiftUser';
    document.getElementById('inject-text').value = '';
  } else if (mode === 'follow') {
    document.getElementById('inject-event-type').value = 'FOLLOW';
    document.getElementById('inject-priority').value = 'NORMAL';
    document.getElementById('inject-viewer-id').value = 'follow-user';
    document.getElementById('inject-username').value = 'FollowUser';
    document.getElementById('inject-text').value = '';
  }
  wizardLog(`Inject preset applied: ${mode}`);
}

async function loadDiagnostics() {
  try {
    const diagnostics = await getJson('/api/runtime/diagnostics');
    lastDiagnosticsState = diagnostics;
    renderWorkerStatus(diagnostics.workers || {});
    renderDetail('runtime-diagnostics-detail', diagnostics);
    renderDetail('runtime-metrics-detail', diagnostics.metrics || {});
    renderIssues(diagnostics.issues || []);
    renderHotStateSummary(diagnostics.hot_state_summary || {});
    renderEnvironmentSummary();
    wizardLog('Runtime diagnostics refreshed.');
  } catch (err) {
    controlLog(`diagnostics load failed: ${err.message}`);
  }
}

async function injectRuntimeEvent() {
  try {
    const payload = {
      event_type: document.getElementById('inject-event-type').value.trim() || 'CHAT_MESSAGE',
      priority: document.getElementById('inject-priority').value.trim() || 'NORMAL',
      viewer_id: document.getElementById('inject-viewer-id').value.trim(),
      username: document.getElementById('inject-username').value.trim(),
      text: document.getElementById('inject-text').value.trim(),
    };
    const result = await postJson('/api/runtime/inject-event', 'POST', payload);
    document.getElementById('inject-status').textContent = `Injected ${result.event_type} (${result.event_id})`;
    controlLog(`event injected: ${result.event_type} ${result.event_id}`);
    await loadDiagnostics();
  } catch (err) {
    document.getElementById('inject-status').textContent = `Injection failed: ${err.message}`;
    controlLog(`event inject failed: ${err.message}`);
  }
}

async function runRuntimeSmoke() {
  try {
    applyInjectPreset('chat');
    await injectRuntimeEvent();
    applyInjectPreset('follow');
    await injectRuntimeEvent();
    setDashboardBanner('Runtime smoke chain injected successfully.', 'ok');
    wizardLog('Runtime smoke chain completed.');
    showTab('events');
  } catch (err) {
    setDashboardBanner(`Runtime smoke failed: ${err.message}`, 'error');
    wizardLog(`Runtime smoke failed: ${err.message}`);
  }
}

async function loadRuntimeExplorer(mode) {
  try {
    let result;
    if (mode === 'overview') {
      result = await getJson('/api/runtime/overview');
      renderDetail('runtime-explorer-detail', result);
    } else if (mode === 'hot_state') {
      result = await getJson('/api/runtime/hot-state');
      renderDetail('runtime-explorer-detail', result);
    } else if (mode === 'sessions') {
      result = await getJson('/api/runtime/sessions');
      renderDetail('runtime-explorer-detail', result.sessions || result);
    } else if (mode === 'viewers') {
      result = await getJson('/api/runtime/viewers');
      renderDetail('runtime-explorer-detail', result.viewers || result);
    } else if (mode === 'history') {
      result = await getJson('/api/runtime/history/conversation?limit=10&offset=0');
      renderDetail('runtime-explorer-detail', result.items || result);
    } else if (mode === 'audit') {
      result = await getJson('/api/runtime/storage/audit?limit=10&offset=0');
      renderDetail('runtime-explorer-detail', result.items || result);
    }
    wizardLog(`Runtime explorer loaded: ${mode}`);
  } catch (err) {
    controlLog(`runtime explorer failed: ${err.message}`);
  }
}

function fillConfigForm(configPath, config) {
  lastConfigState = {config_path: configPath, config_json: config};
  document.getElementById('config-path').textContent = configPath || 'nova.config.json';
  document.getElementById('config-display').textContent = configSummary(config || {});
  document.getElementById('config-json-preview').value = JSON.stringify(config || {}, null, 2);
  document.getElementById('cfg-port').value = config.port Open 8765;
  document.getElementById('cfg-runtime-role').value = config.runtime?.role || 'all';
  document.getElementById('cfg-auth-enabled').checked = !!config.auth?.enabled;
  document.getElementById('cfg-llm-provider').value = config.llm?.provider || 'ollama';
  document.getElementById('cfg-llm-base-url').value = config.llm?.base_url || '';
  document.getElementById('cfg-llm-model').value = config.llm?.model || '';
  document.getElementById('cfg-character-path').value = config.character?.path || '';
  document.getElementById('cfg-voice-backend').value = config.voice?.backend || '';
  document.getElementById('cfg-voice-id').value = config.voice?.voice_id || '';
  document.getElementById('cfg-voice-fallback-chain').value = (config.voice?.fallback_chain || []).join(',');
  document.getElementById('cfg-avatar-enabled').checked = !!config.avatar?.enabled;
  document.getElementById('cfg-avatar-driver').value = config.avatar?.driver || 'web';
  document.getElementById('cfg-output-strategy').value = config.avatar?.output_strategy || 'voice_only';
  document.getElementById('cfg-knowledge-enabled').checked = !!config.knowledge?.enabled;
  document.getElementById('cfg-knowledge-embedding-backend').value = config.knowledge?.embedding_backend || 'ollama';
  document.getElementById('cfg-knowledge-embedding-model').value = config.knowledge?.embedding_model || '';
  document.getElementById('cfg-knowledge-vector-backend').value = config.knowledge?.vector_backend || 'memory';
  document.getElementById('cfg-knowledge-top-k').value = config.knowledge?.retrieval_top_k Open 3;
  document.getElementById('cfg-knowledge-score-threshold').value = config.knowledge?.retrieval_score_threshold Open 0.25;
  document.getElementById('cfg-persistence-backend').value = config.persistence?.backend || 'json';
  document.getElementById('cfg-postgres-url').value = config.persistence?.postgres_url || '';
  document.getElementById('cfg-redis-url').value = config.persistence?.redis_url || '';
  document.getElementById('cfg-tools-enabled').checked = !!config.tools?.enabled;
  document.getElementById('cfg-tools-max-rounds').value = config.tools?.max_rounds Open 2;
  document.getElementById('cfg-nlu-confidence-threshold').value = config.nlu?.confidence_threshold Open 0.6;
  document.getElementById('cfg-memory-enabled').checked = !!config.memory?.enabled;
  document.getElementById('cfg-memory-working-maxlen').value = config.memory?.working_memory_maxlen Open 50;
  document.getElementById('cfg-consolidation-enabled').checked = !!config.consolidation?.enabled;
  document.getElementById('cfg-consolidation-idle-only').checked = !!config.consolidation?.run_only_when_idle;
  document.getElementById('cfg-consolidation-interval-s').value = config.consolidation?.interval_s Open 300;
  document.getElementById('cfg-consolidation-min-entries').value = config.consolidation?.min_entries Open 20;
  document.getElementById('cfg-consolidation-min-idle-s').value = config.consolidation?.min_idle_s Open 60;
  renderEnvironmentSummary();
  renderStartupChecklist();
}

function collectConfigPayload() {
  return {
    port: Number(document.getElementById('cfg-port').value || '8765'),
    llm: {
      provider: document.getElementById('cfg-llm-provider').value.trim() || 'ollama',
      base_url: document.getElementById('cfg-llm-base-url').value.trim(),
      model: document.getElementById('cfg-llm-model').value.trim(),
    },
    voice: {
      backend: document.getElementById('cfg-voice-backend').value.trim() || 'edge_tts',
      voice_id: document.getElementById('cfg-voice-id').value.trim(),
      fallback_chain: document.getElementById('cfg-voice-fallback-chain').value.split(',').map((item) => item.trim()).filter(Boolean),
    },
    character: {
      path: document.getElementById('cfg-character-path').value.trim(),
    },
    knowledge: {
      enabled: document.getElementById('cfg-knowledge-enabled').checked,
      embedding_backend: document.getElementById('cfg-knowledge-embedding-backend').value.trim() || 'ollama',
      embedding_model: document.getElementById('cfg-knowledge-embedding-model').value.trim(),
      vector_backend: document.getElementById('cfg-knowledge-vector-backend').value.trim() || 'memory',
      retrieval_top_k: Number(document.getElementById('cfg-knowledge-top-k').value || '3'),
      retrieval_score_threshold: Number(document.getElementById('cfg-knowledge-score-threshold').value || '0.25'),
    },
    memory: {
      enabled: document.getElementById('cfg-memory-enabled').checked,
      working_memory_maxlen: Number(document.getElementById('cfg-memory-working-maxlen').value || '50'),
    },
    persistence: {
      backend: document.getElementById('cfg-persistence-backend').value.trim() || 'json',
      postgres_url: document.getElementById('cfg-postgres-url').value.trim(),
      redis_url: document.getElementById('cfg-redis-url').value.trim(),
    },
    auth: {
      enabled: document.getElementById('cfg-auth-enabled').checked,
    },
    avatar: {
      enabled: document.getElementById('cfg-avatar-enabled').checked,
      driver: document.getElementById('cfg-avatar-driver').value.trim() || 'web',
      output_strategy: document.getElementById('cfg-output-strategy').value.trim() || 'voice_only',
    },
    runtime: {
      role: document.getElementById('cfg-runtime-role').value.trim() || 'all',
    },
    nlu: {
      confidence_threshold: Number(document.getElementById('cfg-nlu-confidence-threshold').value || '0.6'),
    },
    tools: {
      enabled: document.getElementById('cfg-tools-enabled').checked,
      max_rounds: Number(document.getElementById('cfg-tools-max-rounds').value || '2'),
    },
    consolidation: {
      enabled: document.getElementById('cfg-consolidation-enabled').checked,
      run_only_when_idle: document.getElementById('cfg-consolidation-idle-only').checked,
      interval_s: Number(document.getElementById('cfg-consolidation-interval-s').value || '300'),
      min_entries: Number(document.getElementById('cfg-consolidation-min-entries').value || '20'),
      min_idle_s: Number(document.getElementById('cfg-consolidation-min-idle-s').value || '60'),
    },
  };
}

async function loadCapabilityCatalog() {
  try {
    const result = await getJson('/api/capabilities/catalog');
    renderJsonInto('capability-catalog-preview', result);
    setDashboardBanner('Capability catalog loaded.', 'ok');
  } catch (err) {
    renderJsonInto('capability-catalog-preview', {status: 'error', reason: err.message});
    setDashboardBanner(`Capability catalog failed: ${err.message}`, 'error');
  }
}

async function loadConfigForm() {
  try {
    const result = await getJson('/api/config/current');
    fillConfigForm(result.config_path, result.config_json || {});
    await loadCapabilityCatalog();
    document.getElementById('config-save-status').textContent = 'Settings loaded from disk.';
    setDashboardBanner('Configuration loaded. You can edit and save directly in the Config center.', 'ok');
  } catch (err) {
    controlLog(`config load failed: ${err.message}`);
    document.getElementById('config-save-status').textContent = `Load failed: ${err.message}`;
    setDashboardBanner(`Configuration load failed: ${err.message}`, 'error');
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
    setDashboardBanner(
      result.restart_required
        ? 'Configuration saved. Some changes require restarting the EXE to take effect.'
        : 'Configuration saved. Safe hot-reload settings are already active.',
      result.restart_required ? 'warn' : 'ok'
    );
    await loadConfigForm();
  } catch (err) {
    controlLog(`config save failed: ${err.message}`);
    document.getElementById('config-save-status').textContent = `Save failed: ${err.message}`;
    setDashboardBanner(`Configuration save failed: ${err.message}`, 'error');
  }
}

async function reloadCharacterConfig() {
  try {
    const result = await postJson('/api/config/reload', 'POST', {});
    document.getElementById('config-save-status').textContent = `Character reloaded: ${result.character || 'ok'}`;
    controlLog(`character reload ok: ${result.character || 'ok'}`);
    setDashboardBanner(`Character card reloaded: ${result.character || 'ok'}`, 'ok');
  } catch (err) {
    controlLog(`character reload failed: ${err.message}`);
    document.getElementById('config-save-status').textContent = `Reload failed: ${err.message}`;
    setDashboardBanner(`Character card reload failed: ${err.message}`, 'error');
  }
}

function renderList(elementId, items, fields) {
  const target = document.getElementById(elementId);
  target.innerHTML = '';
  (items || []).forEach((item) => {
    const row = document.createElement('div');
    row.className = 'event-row';
    row.textContent = fields.map((field) => `${field}: ${item[field] Open ''}`).join(' | ');
    target.appendChild(row);
  });
}

function renderActionList(elementId, items, fields, inspector) {
  const target = document.getElementById(elementId);
  target.innerHTML = '';
  if (!(items || []).length) {
    renderEmptyState(elementId, 'No items yet', 'Create a resource or adjust your filters to populate this list.');
    return;
  }
  (items || []).forEach((item) => {
    const row = document.createElement('div');
    row.className = 'list-card';
    const summary = document.createElement('div');
    summary.className = 'flex-1';
    const title = document.createElement('div');
    title.className = 'list-title';
    title.textContent = String(item[fields[0]] Open 'unnamed');
    const meta = document.createElement('div');
    meta.className = 'list-meta';
    meta.textContent = fields.slice(1).map((field) => `${field}: ${item[field] Open ''}`).join(' | ');
    summary.appendChild(title);
    summary.appendChild(meta);
    if (item.status) {
      const badge = document.createElement('span');
      badge.className = 'mt-2 inline-block rounded px-2 py-1 text-[10px] ' + (
        item.status === 'published' ? 'bg-green-500/20 text-green-200' :
        item.status === 'rolled_back' ? 'bg-red-500/20 text-red-200' :
        'bg-amber-500/20 text-amber-200'
      );
      badge.textContent = item.status;
      summary.appendChild(badge);
    }
    const button = document.createElement('button');
    button.className = 'bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-[11px]';
    button.textContent = 'Inspect';
    button.onclick = () => inspector(item);
    row.appendChild(summary);
    row.appendChild(button);
    target.appendChild(row);
  });
}

function renderDetail(elementId, payload) {
  const target = document.getElementById(elementId);
  if (!target) return;
  target.innerHTML = '';
  const pre = document.createElement('pre');
  pre.className = 'json-view';
  pre.textContent = JSON.stringify(payload, null, 2);
  target.appendChild(pre);
}

function renderSimpleRows(elementId, rows) {
  const target = document.getElementById(elementId);
  if (!target) return;
  target.innerHTML = '';
  if (!(rows || []).length) {
    renderEmptyState(elementId, 'Nothing to show', 'This area will populate after the first successful load.');
    return;
  }
  (rows || []).forEach((item) => {
    const row = document.createElement('div');
    row.className = 'list-card';
    row.innerHTML = `<div class="list-meta">${item}</div>`;
    target.appendChild(row);
  });
}

function renderPagination(elementId, key, count) {
  const target = document.getElementById(elementId);
  if (!target) return;
  const state = pageState[key];
  const page = Math.floor(state.offset / state.limit) + 1;
  target.innerHTML = '';
  const prev = document.createElement('button');
  prev.className = 'bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1';
  prev.textContent = 'Prev';
  prev.disabled = state.offset === 0;
  prev.onclick = () => {
    state.offset = Math.max(0, state.offset - state.limit);
    if (key === 'audit') loadAudit(); else refreshControlPlane();
  };
  const next = document.createElement('button');
  next.className = 'bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1';
  next.textContent = 'Next';
  next.disabled = count < state.limit;
  next.onclick = () => {
    state.offset += state.limit;
    if (key === 'audit') loadAudit(); else refreshControlPlane();
  };
  const label = document.createElement('div');
  label.className = 'muted-note';
  label.textContent = `Page ${page} · Showing ${count}`;
  target.appendChild(prev);
  target.appendChild(label);
  target.appendChild(next);
}

function applyConfigPreset(mode) {
  showTab('config');
  loadConfigForm().then(() => {
    if (mode === 'local') {
      document.getElementById('cfg-runtime-role').value = 'all';
      document.getElementById('cfg-auth-enabled').checked = false;
      document.getElementById('cfg-knowledge-enabled').checked = false;
      document.getElementById('cfg-persistence-backend').value = 'json';
      wizardLog('Applied Local Preview preset.');
    } else if (mode === 'control') {
      document.getElementById('cfg-runtime-role').value = 'all';
      document.getElementById('cfg-auth-enabled').checked = true;
      document.getElementById('cfg-persistence-backend').value = 'json';
      document.getElementById('cfg-postgres-url').value = 'postgresql://nova:nova@localhost:5432/nova';
      wizardLog('Applied Control Plane preset.');
    } else if (mode === 'acceptance') {
      document.getElementById('cfg-runtime-role').value = 'all';
      document.getElementById('cfg-auth-enabled').checked = true;
      document.getElementById('cfg-knowledge-enabled').checked = false;
      document.getElementById('cfg-persistence-backend').value = 'json';
      document.getElementById('cfg-postgres-url').value = 'postgresql://nova:nova@localhost:5432/nova';
      document.getElementById('cfg-redis-url').value = 'redis://localhost:6379';
      wizardLog('Applied Acceptance preset.');
    }
    setDashboardBanner(`Preset applied: ${mode}`, 'ok');
  }).catch(() => {});
}

function renderWizardSteps() {
  const target = document.getElementById('wizard-init-steps');
  if (!target) return;
  const steps = [
    {label: 'Step 1 ? Open Config and save the baseline runtime settings', action: () => { showTab('config'); loadConfigForm(); }},
    {label: 'Step 2 ? Create a tenant', action: () => { showTab('control'); scrollIntoViewId('tenant-list'); }},
    {label: 'Step 3 ? Create a role and bind permissions', action: () => { showTab('control'); scrollIntoViewId('role-list'); }},
    {label: 'Step 4 ? Create a user and bind a role', action: () => { showTab('control'); scrollIntoViewId('user-list'); }},
    {label: 'Step 5 ? Create and publish a revision', action: () => { showTab('control'); scrollIntoViewId('revision-list'); }},
    {label: 'Step 6 ? Run Acceptance Mode', action: () => { showTab('guide'); runAcceptanceChecks(); }},
  ];
  target.innerHTML = '';
  steps.forEach((step) => {
    const row = document.createElement('div');
    row.className = 'flex items-center justify-between gap-2 bg-black/10 rounded px-3 py-2';
    const text = document.createElement('div');
    text.textContent = step.label;
    const btn = document.createElement('button');
    btn.className = 'bg-white/10 hover:bg-white/20 text-white rounded px-2 py-1 text-[11px]';
    btn.textContent = 'Go';
    btn.onclick = step.action;
    row.appendChild(text);
    row.appendChild(btn);
    target.appendChild(row);
  });
}

async function runAcceptanceChecks() {
  const target = document.getElementById('acceptance-checks');
  target.innerHTML = '';
  const results = [];
  async function check(label, fn) {
    try {
      const ok = await fn();
      results.push({label, ok, detail: ok ? 'ok' : 'failed'});
    } catch (err) {
      results.push({label, ok: false, detail: err.message});
    }
  }
  await check('Health available', async () => (await fetch('/health')).ok);
  await check('Studio status available', async () => (await getJson('/studio/api/status')).status === 'ok');
  await check('Config load available', async () => !!(await getJson('/api/config/current')).config_path);
  await check('Current user context available', async () => {
    if (!authToken) return false;
    return (await getJson('/api/auth/me')).status === 'ok';
  });
  await check('Effective revision lookup ready', async () => {
    const resourceType = document.getElementById('effective-resource-type').value.trim();
    const resourceId = document.getElementById('effective-resource-id').value.trim();
    if (!resourceType || !resourceId) return false;
    const result = await getJson('/api/control/config-revisions/effective' + queryString({
      tenant_id: document.getElementById('effective-tenant-id').value.trim(),
      resource_type: resourceType,
      resource_id: resourceId,
    }));
    return result.status === 'ok';
  });
  results.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'list-card';
    row.innerHTML = `<div class="flex-1"><div class="list-title">${item.label}</div><div class="list-meta">${item.detail}</div></div><span class="pill ${item.ok ? 'pill-ok' : 'pill-err'}">${item.ok ? 'PASS' : 'FAIL'}</span>`;
    target.appendChild(row);
  });
  lastAcceptanceResults = results;
  wizardLog(`Acceptance checks completed: ${results.filter(r => r.ok).length}/${results.length} passed.`);
}

function openDiagnosticsCenter() {
  showTab('dashboard');
  loadDiagnostics();
  scrollIntoViewId('diagnostics-center');
  setDashboardBanner('Diagnostics center opened.', 'ok');
}

async function exportAcceptanceReport() {
  try {
    if (!lastAcceptanceResults.length) {
      await runAcceptanceChecks();
    }
    const result = await getJson('/api/acceptance/export');
    const report = {
      exported_at: new Date().toISOString(),
      checks: lastAcceptanceResults,
      payload: result,
    };
    const blob = new Blob([JSON.stringify(report, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `nova_acceptance_${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    link.click();
    URL.revokeObjectURL(url);
    wizardLog('Acceptance report exported.');
    setDashboardBanner('Acceptance report exported.', 'ok');
  } catch (err) {
    wizardLog(`Acceptance export failed: ${err.message}`);
    setDashboardBanner(`Acceptance export failed: ${err.message}`, 'error');
  }
}

function renderPlatformSummary(summary, issues) {
  document.getElementById('platform-summary-catalog').textContent = String(summary?.catalog_count Open 0);
  document.getElementById('platform-summary-configured').textContent = String(summary?.configured_count Open 0);
  document.getElementById('platform-summary-healthy').textContent = String(summary?.healthy_count Open 0);
  document.getElementById('platform-summary-issues').textContent = String((issues || []).length + (summary?.disabled_count Open 0));
}

function renderPlatformCatalogRows(items) {
  const target = document.getElementById('platform-catalog');
  target.innerHTML = '';
  if (!(items || []).length) {
    renderEmptyState('platform-catalog', 'No platform metadata', 'Load the platform catalog or templates to start configuring adapters.');
    return;
  }
  (items || []).forEach((item) => {
    const row = document.createElement('div');
    row.className = 'event-row';
    row.innerHTML = `<div class="font-semibold text-white">${item.label || item.platform}</div>
      <div class="text-white/60">${item.summary || ''}</div>
      <div class="text-white/50 mt-1">transport=${item.transport || 'n/a'} | auth=${item.auth_kind || 'n/a'} | modes=${(item.modes || []).join(', ')}</div>`;
    row.onclick = () => {
      document.getElementById('platform-detail-input').value = item.platform;
      loadPlatformDetail();
    };
    target.appendChild(row);
  });
}

function renderPlatformStatusRows(result) {
  const target = document.getElementById('platform-status');
  target.innerHTML = '';
  if (!(result.items || []).length) {
    renderEmptyState('platform-status', 'No configured platforms', 'Apply a platform template or save platform config to populate runtime status.');
    return;
  }
  (result.items || []).forEach((item) => {
    const row = document.createElement('div');
    const runtime = item.runtime || {};
    const validation = item.validation || {};
    const health = runtime.health || 'unknown';
    row.className = 'list-card';
    row.innerHTML = `<div class="flex-1">
      <div class="list-title">${item.catalog?.label || item.platform}</div>
      <div class="list-meta">enabled=${item.configured?.enabled Open true} | priority=${item.configured?.priority Open 100} | mode=${item.configured?.mode || item.catalog?.recommended_mode || 'n/a'} | running=${runtime.running Open false}</div>
      <div class="list-meta">events=${runtime.events_received Open 0} | errors=${runtime.errors Open 0} | last_event_ago_s=${runtime.last_event_ago_s Open 'n/a'} | valid=${validation.valid Open true}</div>
    </div>
    <span class="pill ${health === 'healthy' ? 'pill-ok' : health === 'down' ? 'pill-err' : 'pill-warn'}">${health}</span>`;
    row.onclick = () => {
      document.getElementById('platform-detail-input').value = item.platform;
      loadPlatformStatusDetail(item.platform);
    };
    target.appendChild(row);
  });
  (result.issues || []).forEach((issue) => {
    const row = document.createElement('div');
    row.className = 'event-row text-amber-200';
    row.textContent = `Issue: ${issue}`;
    target.appendChild(row);
  });
}

function renderPlatformDetailPayload(payload) {
  renderJsonInto('platform-detail', payload || {});
}

function renderPlatformTemplateGuide(item) {
  renderPlatformDetailPayload({
    platform: item.platform,
    label: item.label,
    notes: item.notes || {},
    acceptance_checklist: item.acceptance_checklist || [],
    debug_event: item.debug_event || {},
  });
}

async function loadPlatformCatalog() {
  try {
    const result = await getJson('/api/platforms/catalog');
    lastPlatformCatalog = result.items || [];
    renderPlatformCatalogRows(lastPlatformCatalog);
    const select = document.getElementById('platform-template-select');
    select.innerHTML = '';
    lastPlatformCatalog.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.platform;
      option.textContent = `${item.label || item.platform} (${item.platform})`;
      select.appendChild(option);
    });
    if (lastPlatformCatalog[0]) {
      document.getElementById('platform-detail-input').value = lastPlatformCatalog[0].platform;
    }
    renderPlatformSummary({catalog_count: lastPlatformCatalog.length}, []);
    wizardLog('Platform catalog loaded.');
  } catch (err) {
    wizardLog(`Platform catalog failed: ${err.message}`);
  }
}

function applySelectedPlatformTemplate() {
  const select = document.getElementById('platform-template-select');
  const platform = select.value;
  if (!platform) return;
  const item = lastPlatformCatalog.find((entry) => entry.platform === platform);
  if (!item?.template) return;
  document.getElementById('platform-config-editor').value = JSON.stringify(item.template);
  document.getElementById('platform-detail-input').value = platform;
  renderPlatformTemplateGuide(item);
  wizardLog(`Platform template applied: ${platform}`);
}

async function loadPlatformTemplates() {
  try {
    const result = await getJson('/api/platforms/templates');
    lastPlatformCatalog = result.items || [];
    renderPlatformCatalogRows(lastPlatformCatalog.map((item) => ({
      ...item,
      summary: `recommended_mode=${item.notes?.recommended_mode || 'n/a'} | required=${(item.notes?.required_fields || []).join(', ')}`,
      transport: 'template',
      auth_kind: (item.notes?.secret_fields || []).length ? 'has_secrets' : 'none',
      modes: [item.notes?.recommended_mode || 'n/a'],
    })));
    if (result.items?.length) {
      const select = document.getElementById('platform-template-select');
      select.innerHTML = '';
      result.items.forEach((item) => {
        const option = document.createElement('option');
        option.value = item.platform;
        option.textContent = `${item.label || item.platform} template`;
        select.appendChild(option);
      });
      document.getElementById('platform-config-editor').value = result.items.map((item) => JSON.stringify(item.template)).join('\n');
      renderPlatformTemplateGuide(result.items[0]);
    }
    wizardLog('Platform templates loaded into editor.');
  } catch (err) {
    wizardLog(`Platform templates failed: ${err.message}`);
  }
}

async function loadPlatformDetail() {
  try {
    const platform = document.getElementById('platform-detail-input').value.trim();
    if (!platform) {
      renderEmptyState('platform-detail', 'No platform selected', 'Enter a platform id like bilibili or choose one from the catalog.');
      return;
    }
    const result = await getJson(`/api/platforms/catalog/${platform}`);
    renderPlatformDetailPayload(result.item || {});
    wizardLog(`Platform detail loaded: ${platform}`);
  } catch (err) {
    renderErrorState('platform-detail', 'Platform detail failed', err.message);
    wizardLog(`Platform detail failed: ${err.message}`);
  }
}

async function loadPlatformStatusDetail(platform) {
  try {
    const result = await getJson(`/api/platforms/status/${platform}`);
    renderPlatformDetailPayload(result.item || {});
    wizardLog(`Platform status detail loaded: ${platform}`);
  } catch (err) {
    renderPlatformDetailPayload({status: 'error', reason: err.message});
    wizardLog(`Platform status detail failed: ${err.message}`);
  }
}

async function loadPlatformExtensionSpec() {
  try {
    const result = await getJson('/api/platforms/extensions/spec');
    renderJsonInto('platform-extension-spec', result);
    wizardLog('Platform extension spec loaded.');
  } catch (err) {
    renderErrorState('platform-extension-spec', 'Extension spec failed', err.message);
    wizardLog(`Platform extension spec failed: ${err.message}`);
  }
}

function populateLibrarySelectors() {
  const kindSelect = document.getElementById('library-kind-select');
  const itemSelect = document.getElementById('library-item-select');
  if (!kindSelect || !itemSelect || !lastLibraryCatalog) return;
  kindSelect.innerHTML = '';
  Object.keys(lastLibraryCatalog.templates || {}).forEach((kind) => {
    const option = document.createElement('option');
    option.value = kind;
    option.textContent = kind;
    kindSelect.appendChild(option);
  });
  updateLibraryItemOptions();
}

function updateLibraryItemOptions() {
  const kind = document.getElementById('library-kind-select')?.value;
  const itemSelect = document.getElementById('library-item-select');
  if (!kind || !itemSelect || !lastLibraryCatalog) return;
  itemSelect.innerHTML = '';
  const items = lastLibraryCatalog.templates?.[kind]?.items || [];
  items.forEach((item) => {
    const option = document.createElement('option');
    option.value = item.id;
    option.textContent = item.title || item.id;
    itemSelect.appendChild(option);
  });
}

async function loadLibraryCatalog() {
  try {
    const result = await getJson('/api/library/catalog');
    lastLibraryCatalog = result;
    populateLibrarySelectors();
    renderJsonInto('library-preview', result.templates || {});
    wizardLog('Template library catalog loaded.');
  } catch (err) {
    renderErrorState('library-preview', 'Template library failed', err.message);
    wizardLog(`Template library failed: ${err.message}`);
  }
}

async function loadLibraryTemplateDetail() {
  try {
    const kind = document.getElementById('library-kind-select').value;
    const itemId = document.getElementById('library-item-select').value;
    if (!kind || !itemId) {
      renderEmptyState('library-preview', 'No template selected', 'Pick a template kind and item before previewing.');
      return;
    }
    const result = await getJson(`/api/library/templates/${kind}/${itemId}`);
    renderJsonInto('library-preview', result.item || {});
    wizardLog(`Library template loaded: ${kind}/${itemId}`);
  } catch (err) {
    renderErrorState('library-preview', 'Template preview failed', err.message);
    wizardLog(`Library template failed: ${err.message}`);
  }
}

async function applyLibraryTemplate() {
  try {
    const kind = document.getElementById('library-kind-select').value;
    const itemId = document.getElementById('library-item-select').value;
    const result = await getJson(`/api/library/templates/${kind}/${itemId}`);
    const item = result.item || {};
    if (kind === 'platforms') {
      document.getElementById('platform-config-editor').value = item.content_text || '';
      setDashboardBanner(`Applied platform template: ${item.title || item.id}`, 'ok');
    } else if (kind === 'characters') {
      showTab('config');
      const field = document.getElementById('cfg-character-path');
      if (field) field.value = item.path || '';
      setDashboardBanner(`Selected character template: ${item.title || item.id}`, 'ok');
    } else if (kind === 'deploy') {
      const preview = document.getElementById('config-json-preview');
      if (preview) preview.value = JSON.stringify(item.content_json || {content_text: item.content_text || ''}, null, 2);
      const cfg = item.content_json || {};
      if (cfg.runtime?.role) document.getElementById('cfg-runtime-role').value = cfg.runtime.role;
      if (typeof cfg.auth?.enabled === 'boolean') document.getElementById('cfg-auth-enabled').checked = cfg.auth.enabled;
      if (cfg.persistence?.backend) document.getElementById('cfg-persistence-backend').value = cfg.persistence.backend;
      if (cfg.persistence?.postgres_url) document.getElementById('cfg-postgres-url').value = cfg.persistence.postgres_url;
      showTab('config');
      setDashboardBanner(`Loaded ${kind} template: ${item.title || item.id}`, 'ok');
    } else if (kind === 'scenarios') {
      const scenario = item.content_json || {};
      if (scenario.ai_profile) {
        document.getElementById('cfg-knowledge-enabled').checked = !!scenario.ai_profile.knowledge_enabled;
        document.getElementById('cfg-tools-enabled').checked = !!scenario.ai_profile.tools_enabled;
      }
      if (scenario.character_template) {
        const characterResult = await getJson(`/api/library/templates/characters/${scenario.character_template}`);
        document.getElementById('cfg-character-path').value = characterResult.item?.path || '';
      }
      if (scenario.platform_template) {
        const platformResult = await getJson(`/api/library/templates/platforms/${scenario.platform_template}`);
        document.getElementById('platform-config-editor').value = platformResult.item?.content_text || '';
      }
      const preview = document.getElementById('config-json-preview');
      if (preview) preview.value = JSON.stringify(scenario, null, 2);
      showTab('config');
      setDashboardBanner(`Scenario applied: ${item.title || item.id}`, 'ok');
    } else if (kind === 'prompts') {
      const preview = document.getElementById('config-json-preview');
      if (preview) preview.value = JSON.stringify(item.content_json || {content_text: item.content_text || ''}, null, 2);
      showTab('config');
      setDashboardBanner(`Prompt template loaded: ${item.title || item.id}`, 'ok');
    }
    renderJsonInto('library-preview', item);
    wizardLog(`Library template applied: ${kind}/${itemId}`);
  } catch (err) {
    wizardLog(`Apply library template failed: ${err.message}`);
    setDashboardBanner(`Apply library template failed: ${err.message}`, 'error');
  }
}

async function loadExtensionDocCatalog() {
  try {
    const result = await getJson('/api/library/extensions/docs');
    const select = document.getElementById('extension-doc-select');
    if (!select) return;
    select.innerHTML = '';
    (result.items || []).forEach((item) => {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = item.title || item.id;
      select.appendChild(option);
    });
    if ((result.items || []).length) {
      await loadExtensionDocDetail();
    } else {
      renderEmptyState('extension-doc-preview', 'No extension docs yet', 'Add open-platform docs to help third-party integrators onboard faster.');
    }
    wizardLog('Extension docs catalog loaded.');
  } catch (err) {
    renderErrorState('extension-doc-preview', 'Extension docs catalog failed', err.message);
    wizardLog(`Extension docs catalog failed: ${err.message}`);
  }
}

async function loadExtensionDocDetail() {
  try {
    const itemId = document.getElementById('extension-doc-select').value;
    if (!itemId) {
      renderEmptyState('extension-doc-preview', 'No extension doc selected', 'Choose a doc to inspect the open-platform contract.');
      return;
    }
    const result = await getJson(`/api/library/extensions/docs/${itemId}`);
    renderJsonInto('extension-doc-preview', result.item || {});
    wizardLog(`Extension doc loaded: ${itemId}`);
  } catch (err) {
    renderErrorState('extension-doc-preview', 'Extension doc failed', err.message);
    wizardLog(`Extension doc failed: ${err.message}`);
  }
}

async function loadPlatformConfig() {
  try {
    const platform = document.getElementById('platform-config-filter').value.trim();
    const result = await getJson('/api/platforms/config' + queryString({platform}));
    const items = result.items || [];
    document.getElementById('platform-config-editor').value = items.map((item) => JSON.stringify(item)).join('\n');
    document.getElementById('platform-config-status').textContent = `Loaded ${items.length} platform config item(s).`;
    wizardLog('Platform config loaded.');
  } catch (err) {
    wizardLog(`Platform config load failed: ${err.message}`);
  }
}

function parsePlatformEditor() {
  const raw = document.getElementById('platform-config-editor').value.trim();
  if (!raw) return [];
  const parsed = JSON.parse(`[${raw.split(/\n+/).map((line) => line.trim()).filter(Boolean).join(',')}]`);
  return Array.isArray(parsed) ? parsed : [];
}

async function validatePlatformConfig() {
  try {
    const items = parsePlatformEditor();
    const result = await postJson('/api/platforms/validate-config', 'POST', {items});
    renderSimpleRows('platform-status', (result.items || []).map((item) =>
      `${item.platform} | valid=${item.valid} | reason=${item.reason || 'ok'} | mode=${item.recommended_mode || 'n/a'}`
    ));
    document.getElementById('platform-config-status').textContent = 'Validation completed.';
    wizardLog('Platform config validated.');
  } catch (err) {
    document.getElementById('platform-config-status').textContent = `Validation failed: ${err.message}`;
    wizardLog(`Platform validation failed: ${err.message}`);
  }
}

async function savePlatformConfig() {
  try {
    const items = parsePlatformEditor();
    const result = await postJson('/api/platforms/config', 'POST', {items});
    document.getElementById('platform-config-status').textContent =
      `Saved ${result.count} platform config item(s). Restart required=${result.restart_required} | platforms=${(result.platforms || []).join(', ')}`;
    wizardLog('Platform config saved.');
  } catch (err) {
    document.getElementById('platform-config-status').textContent = `Save failed: ${err.message}`;
    wizardLog(`Platform config save failed: ${err.message}`);
  }
}

async function reloadPlatformRuntime() {
  try {
    const result = await postJson('/api/platforms/reload', 'POST', {});
    document.getElementById('platform-config-status').textContent = `Reloaded ${result.count} platform adapter(s).`;
    await loadPlatformStatus();
    wizardLog('Platform runtime reloaded.');
  } catch (err) {
    document.getElementById('platform-config-status').textContent = `Reload failed: ${err.message}`;
    wizardLog(`Platform runtime reload failed: ${err.message}`);
  }
}

async function loadPlatformStatus() {
  try {
    const result = await getJson('/api/platforms/status');
    renderPlatformSummary(result.summary || {}, result.issues || []);
    renderPlatformStatusRows(result);
    wizardLog('Platform status loaded.');
  } catch (err) {
    wizardLog(`Platform status failed: ${err.message}`);
  }
}

function applyPlatformDebugPreset(platform) {
  document.getElementById('platform-debug-name').value = platform;
  document.getElementById('platform-debug-event-type').value = 'CHAT_MESSAGE';
  document.getElementById('platform-debug-priority').value = 'NORMAL';
  document.getElementById('platform-debug-trace-id').value = `${platform}-trace`;
  document.getElementById('platform-debug-viewer-id').value = `${platform}-viewer`;
  document.getElementById('platform-debug-username').value = `${platform}-tester`;
  document.getElementById('platform-debug-text').value = `${platform} runtime platform debug event`;
  document.getElementById('platform-debug-payload').value = '';
  wizardLog(`Platform debug preset applied: ${platform}`);
}

async function sendPlatformTestEvent() {
  try {
    const rawPayload = document.getElementById('platform-debug-payload').value.trim();
    const payload = {
      platform: document.getElementById('platform-debug-name').value.trim() || 'bilibili',
      event_type: document.getElementById('platform-debug-event-type').value.trim() || 'CHAT_MESSAGE',
      priority: document.getElementById('platform-debug-priority').value.trim() || 'NORMAL',
      trace_id: document.getElementById('platform-debug-trace-id').value.trim(),
      viewer_id: document.getElementById('platform-debug-viewer-id').value.trim(),
      username: document.getElementById('platform-debug-username').value.trim(),
      text: document.getElementById('platform-debug-text').value.trim(),
    };
    if (rawPayload) {
      payload.payload = JSON.parse(rawPayload);
    }
    const result = await postJson('/api/platforms/test-event', 'POST', payload);
    document.getElementById('platform-debug-status').textContent =
      `Test event sent: ${result.source} / ${result.event_type} / ${result.event_id} / priority=${result.priority}`;
    renderJsonInto('platform-detail', result);
    wizardLog(`Platform test event sent: ${result.source}`);
  } catch (err) {
    document.getElementById('platform-debug-status').textContent = `Test event failed: ${err.message}`;
    wizardLog(`Platform test event failed: ${err.message}`);
  }
}

async function loadAiEvalReport() {
  try {
    const result = await getJson('/api/ai/eval/latest');
    const report = result.report || {};
    const summary = document.getElementById('ai-eval-summary');
    summary.innerHTML = '';
    const rows = [
      `Dataset: ${report.dataset || 'n/a'}`,
      `Total: ${report.total Open 0}`,
      `Passed: ${report.passed Open 0}`,
      `Failed: ${report.failed Open 0}`,
    ];
    rows.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'event-row';
      row.textContent = item;
      summary.appendChild(row);
    });
    renderDetail('ai-eval-detail', report.results || report);
    wizardLog('AI eval report loaded.');
  } catch (err) {
    wizardLog(`AI eval report failed: ${err.message}`);
  }
}

async function previewRouting() {
  try {
    const text = document.getElementById('ai-routing-input').value.trim();
    const emotion = document.getElementById('ai-routing-emotion').value.trim();
    const result = await postJson('/api/ai/routing-preview', 'POST', {text, emotion});
    renderDetail('ai-eval-detail', result);
    wizardLog('AI routing preview generated.');
  } catch (err) {
    wizardLog(`AI routing preview failed: ${err.message}`);
  }
}

async function refreshControlPlane() {
  try {
    const tenantFilter = document.getElementById('tenant-filter-id')?.value || '';
    const roleTenantFilter = document.getElementById('role-filter-tenant-id')?.value || '';
    const userTenantFilter = document.getElementById('user-filter-tenant-id')?.value || '';
    const userStatusFilter = document.getElementById('user-filter-status')?.value || '';
    const revisionTenantFilter = document.getElementById('revision-filter-tenant-id')?.value || '';
    const revisionTypeFilter = document.getElementById('revision-filter-resource-type')?.value || '';
    const revisionResourceFilter = document.getElementById('revision-filter-resource-id')?.value || '';
    const revisionStatusFilter = document.getElementById('revision-filter-status')?.value || '';
    const [tenants, roles, revisions, permissions, users] = await Promise.all([
      getJson('/api/control/tenants' + queryString({limit: pageState.tenants.limit, offset: pageState.tenants.offset, tenant_id: tenantFilter})),
      getJson('/api/control/roles' + queryString({limit: pageState.roles.limit, offset: pageState.roles.offset, tenant_id: roleTenantFilter})),
      getJson('/api/control/config-revisions' + queryString({
        limit: pageState.revisions.limit,
        offset: pageState.revisions.offset,
        tenant_id: revisionTenantFilter,
        resource_type: revisionTypeFilter,
        resource_id: revisionResourceFilter,
        status: revisionStatusFilter,
      })),
      getJson('/api/control/permissions' + queryString({limit: pageState.permissions.limit, offset: pageState.permissions.offset})),
      getJson('/api/control/users' + queryString({limit: pageState.users.limit, offset: pageState.users.offset, tenant_id: userTenantFilter, status: userStatusFilter})),
    ]);
    renderActionList('tenant-list', tenants.items || [], ['id', 'slug', 'status', 'plan'], (item) => inspectTenant(item.id));
    renderActionList('role-list', roles.items || [], ['id', 'tenant_id', 'name', 'scope'], (item) => inspectRole(item.id));
    renderActionList('revision-list', revisions.items || [], ['id', 'resource_type', 'resource_id', 'revision_no', 'status'], (item) => inspectRevision(item.id));
    renderActionList('permission-list', permissions.items || [], ['id', 'code', 'resource', 'action'], (item) => inspectPermission(item.id));
    renderActionList('user-list', users.items || [], ['id', 'tenant_id', 'email', 'status'], (item) => inspectUser(item.id));
    renderPagination('tenant-pagination', 'tenants', tenants.count || (tenants.items || []).length);
    renderPagination('role-pagination', 'roles', roles.count || (roles.items || []).length);
    renderPagination('revision-pagination', 'revisions', revisions.count || (revisions.items || []).length);
    renderPagination('permission-pagination', 'permissions', permissions.count || (permissions.items || []).length);
    renderPagination('user-pagination', 'users', users.count || (users.items || []).length);
  } catch (err) {
    controlLog(`refresh failed: ${err.message}`);
  }
}

async function inspectTenant(tenantId) {
  try {
    const result = await getJson(`/api/control/tenants/${tenantId}`);
    renderDetail('resource-detail', result.item || result);
  } catch (err) {
    controlLog(`tenant detail failed: ${err.message}`);
  }
}

async function inspectRole(roleId) {
  try {
    const result = await getJson(`/api/control/roles/${roleId}`);
    renderDetail('resource-detail', result.item || result);
  } catch (err) {
    controlLog(`role detail failed: ${err.message}`);
  }
}

async function inspectUser(userId) {
  try {
    const result = await getJson(`/api/control/users/${userId}`);
    renderDetail('resource-detail', result.item || result);
  } catch (err) {
    controlLog(`user detail failed: ${err.message}`);
  }
}

async function inspectPermission(permissionId) {
  try {
    const result = await getJson(`/api/control/permissions/${permissionId}`);
    renderDetail('resource-detail', result.item || result);
  } catch (err) {
    controlLog(`permission detail failed: ${err.message}`);
  }
}

async function inspectRevision(revisionId) {
  try {
    const result = await getJson(`/api/control/config-revisions/${revisionId}`);
    renderDetail('resource-detail', result.item || result);
  } catch (err) {
    controlLog(`revision detail failed: ${err.message}`);
  }
}

async function loadEffectiveRevision() {
  try {
    const tenantId = document.getElementById('effective-tenant-id').value.trim();
    const resourceType = document.getElementById('effective-resource-type').value.trim() || document.getElementById('revision-filter-resource-type').value.trim();
    const resourceId = document.getElementById('effective-resource-id').value.trim() || document.getElementById('revision-filter-resource-id').value.trim();
    const result = await getJson('/api/control/config-revisions/effective' + queryString({
      tenant_id: tenantId,
      resource_type: resourceType,
      resource_id: resourceId,
    }));
    renderDetail('effective-revision-detail', result.item || result);
    renderDetail('resource-detail', result.item || result);
  } catch (err) {
    controlLog(`effective revision failed: ${err.message}`);
    document.getElementById('effective-revision-detail').textContent = `No effective revision: ${err.message}`;
  }
}

async function loadAudit() {
  try {
    const result = await getJson('/api/control/audit' + queryString({
      limit: pageState.audit.limit,
      offset: pageState.audit.offset,
      action: document.getElementById('audit-filter-action').value,
      resource_type: document.getElementById('audit-filter-resource-type').value,
      resource_id: document.getElementById('audit-filter-resource-id').value,
    }));
    renderActionList('audit-list', result.items || [], ['action', 'resource_type', 'resource_id'], (item) => renderDetail('resource-detail', item));
    renderPagination('audit-pagination', 'audit', result.count || (result.items || []).length);
  } catch (err) {
    controlLog(`audit load failed: ${err.message}`);
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
    operator: document.getElementById('revision-operator').value.trim(),
    note: document.getElementById('revision-note').value.trim(),
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
    if (!confirm(`Publish revision ${revisionId}? This will replace the current effective revision for the same resource.`)) {
      return;
    }
    const result = await postJson(`/api/control/config-revisions/${revisionId}/publish`, 'POST', {
      operator: document.getElementById('revision-operator').value.trim() || 'studio',
      note: document.getElementById('revision-note').value.trim(),
    });
    controlLog(`revision published: ${result.id}`);
    await refreshControlPlane();
  } catch (err) {
    controlLog(`revision publish failed: ${err.message}`);
  }
}

async function rollbackRevision() {
  try {
    const revisionId = document.getElementById('revision-id').value;
    if (!confirm(`Rollback revision ${revisionId}? This will mark the published version as rolled back.`)) {
      return;
    }
    const result = await postJson(`/api/control/config-revisions/${revisionId}/rollback`, 'POST', {
      operator: document.getElementById('revision-operator').value.trim() || 'studio',
      note: document.getElementById('revision-note').value.trim(),
    });
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
    const pill = document.getElementById('current-user-pill');
    if (pill) pill.className = 'pill pill-warn';
    document.getElementById('dash-auth-user').textContent = 'anonymous';
    document.getElementById('dash-auth-tenant').textContent = 'n/a';
    document.getElementById('dash-auth-roles').textContent = 'none';
    document.getElementById('dash-auth-permission-count').textContent = '0';
    document.getElementById('auth-user-id').textContent = 'anonymous';
    document.getElementById('auth-tenant-scope').textContent = 'n/a';
    document.getElementById('auth-role-list').textContent = 'none';
    document.getElementById('auth-permission-list').innerHTML = '';
    renderStartupChecklist();
    return;
  }
  try {
    const me = await getJson('/api/auth/me');
    const user = me.user || {};
    const current = document.getElementById('current-user');
    const pill = document.getElementById('current-user-pill');
    if (current) {
      const tenant = user.tenant_id || (user.tenant_ids || []).join(',');
      current.textContent = `${user.id || 'unknown'} @ ${tenant || 'n/a'}`;
    }
    if (pill) pill.className = 'pill pill-ok';
    document.getElementById('dash-auth-user').textContent = user.id || 'unknown';
    document.getElementById('dash-auth-tenant').textContent = user.tenant_id || (user.tenant_ids || []).join(',') || 'n/a';
    document.getElementById('dash-auth-roles').textContent = (user.roles || []).join(', ') || 'none';
    document.getElementById('dash-auth-permission-count').textContent = String((user.permissions || []).length);
    document.getElementById('auth-user-id').textContent = user.id || 'unknown';
    document.getElementById('auth-tenant-scope').textContent = user.tenant_id || (user.tenant_ids || []).join(',') || 'n/a';
    document.getElementById('auth-role-list').textContent = (user.roles || []).join(', ') || 'none';
    const permList = document.getElementById('auth-permission-list');
    permList.innerHTML = '';
    (user.permissions || []).forEach((permission) => {
      const row = document.createElement('div');
      row.className = 'list-card';
      row.innerHTML = `<div class="list-meta">${permission}</div>`;
      permList.appendChild(row);
    });
    renderStartupChecklist();
  } catch (err) {
    controlLog(`auth refresh failed: ${err.message}`);
    const pill = document.getElementById('current-user-pill');
    if (pill) pill.className = 'pill pill-warn';
    setDashboardBanner(`User context refresh failed: ${err.message}`, 'warn');
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
    setDashboardBanner(`Login succeeded: ${userId}`, 'ok');
  } catch (err) {
    controlLog(`login failed: ${err.message}`);
    setDashboardBanner(`Login failed: ${err.message}`, 'error');
  }
}

function studioLogout() {
  authToken = '';
  localStorage.removeItem('nova_studio_token');
  const current = document.getElementById('current-user');
  if (current) current.textContent = 'anonymous';
  const pill = document.getElementById('current-user-pill');
  if (pill) pill.className = 'pill pill-warn';
  document.getElementById('dash-auth-user').textContent = 'anonymous';
  document.getElementById('dash-auth-tenant').textContent = 'n/a';
  document.getElementById('dash-auth-roles').textContent = 'none';
  document.getElementById('dash-auth-permission-count').textContent = '0';
  controlLog('logged out');
  setDashboardBanner('Signed out. Log in again whenever you need control-plane permissions.', 'warn');
  renderStartupChecklist();
}

// Periodic health check
setInterval(async () => {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    lastHealthState = d;
    document.getElementById('blocks').textContent = d.safety?.blocks || 0;
    document.getElementById('queue').textContent = d.bus?.queue_depth || 0;
    document.getElementById('consumer-lag').textContent = d.eventbus?.lag || 0;
    document.getElementById('pending').textContent = d.eventbus?.pending || 0;
    document.getElementById('retries').textContent = d.eventbus?.retries || 0;
    document.getElementById('dlq').textContent = d.eventbus?.dlq_length || 0;
    document.getElementById('char-name').textContent = d.character || 'NOVA';
    document.getElementById('platforms').textContent = Object.keys(d.platforms || {}).length;
    const uptime = Math.floor((Date.now() - startTime) / 1000);
    const m = Math.floor(uptime / 60), s = uptime % 60;
    document.getElementById('uptime').textContent = `${m}m ${s}s`;
    renderEnvironmentSummary();
    renderStartupChecklist();
  } catch(e) {}
}, 5000);

setInterval(async () => {
  try {
    const d = await getJson('/studio/api/status');
    lastStudioStatus = d;
    document.getElementById('runtime-role').textContent = d.runtime?.role || 'unknown';
    document.getElementById('runtime-instance').textContent = d.runtime?.instance_name || 'unknown';
    document.getElementById('runtime-session').textContent = d.runtime?.session_id || 'unknown';
    document.getElementById('runtime-hot').textContent = String(d.runtime?.hot_state || false);
    document.getElementById('conv-count').textContent = d.history?.conversation_count || 0;
    document.getElementById('safety-count').textContent = d.history?.safety_count || 0;

    const preview = document.getElementById('history-preview');
    preview.innerHTML = '';
    const items = d.history_preview || [];
    if (!items.length) {
      renderEmptyState('history-preview', 'No persisted history yet', 'Trigger a runtime event or acceptance flow to populate history preview.');
    }
    items.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'list-card';
      row.innerHTML = `<div class="flex-1"><div class="list-title">${item.kind}</div><div class="list-meta">${item.text}</div></div>`;
      preview.appendChild(row);
    });
    if (d.workers) {
      renderWorkerStatus(d.workers);
      lastDiagnosticsState = {workers: d.workers};
    }
    renderIssues(d.issues || []);
    renderHotStateSummary(d.summary || {});
    renderEnvironmentSummary();
    renderStartupChecklist();
  } catch(e) {}
}, 5000);

setInterval(refreshControlPlane, 10000);
refreshCurrentUser();
refreshControlPlane();
loadConfigForm();
renderWizardSteps();
loadDiagnostics();
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
    from apps.nova_server.main import _runtime_overview_payload
    overview = await _runtime_overview_payload(nova)
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
        "bus": overview["health"]["bus"],
        "workers": overview["workers"],
        "summary": overview["hot_state_summary"] or {},
        "history": overview["history"],
        "history_preview": overview["history_preview"],
        "issues": overview["issues"],
        "metrics": overview["metrics"],
        "effective_revision": overview["effective_revision"],
    })
