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

from fastapi import APIRouter
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
    <div class="mt-auto text-[10px] text-white/30">v1.0.0</div>
  </div>

  <!-- Main -->
  <div class="flex-1 overflow-auto p-6">
    <!-- Header -->
    <div class="flex items-center gap-3 mb-6">
      <span id="status-dot" class="dot-ok"></span>
      <span class="text-sm font-semibold" id="char-name">NOVA</span>
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
      <div class="card p-4">
        <div class="text-[10px] text-white/40 uppercase tracking-wider mb-3">Character Config</div>
        <div class="text-xs text-white/60" id="config-display">Loading…</div>
      </div>
    </div>
  </div>
</div>

<script>
const ws = new WebSocket(`ws://${location.host}/ws/control`);
const eventList = document.getElementById('event-list');
const MAX_EVENTS = 200;
let startTime = Date.now();

function showTab(name) {
  ['dashboard','events','config'].forEach(t => {
    document.getElementById('tab-'+t).style.display = t===name ? '' : 'none';
  });
}

function clearEvents() { eventList.innerHTML = ''; }

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

// Periodic health check
setInterval(async () => {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    document.getElementById('blocks').textContent = d.safety?.blocks || 0;
    document.getElementById('queue').textContent = d.bus?.queue_depth || 0;
    document.getElementById('char-name').textContent = d.character || 'NOVA';
    const uptime = Math.floor((Date.now() - startTime) / 1000);
    const m = Math.floor(uptime / 60), s = uptime % 60;
    document.getElementById('uptime').textContent = `${m}m ${s}s`;
  } catch(e) {}
}, 5000);
</script>
</body>
</html>"""


@router.get("/", response_class=HTMLResponse)
async def studio_dashboard():
    """Serve the Nova Studio dashboard."""
    return HTMLResponse(STUDIO_HTML)


@router.get("/api/status")
async def studio_status():
    """Get current system status for Studio."""
    return JSONResponse({"status": "ok"})
