"""
ACME Booking Travel (ABT) — dual-region FastAPI server.

Two regional workers (us-west-2 and us-east-1) share a single peered Aurora DSQL cluster.
Each worker:
  - Checks the workshop_chaos table on every request; refuses if disabled (503)
  - Runs the full booking saga via SagaOrchestrator
  - Exposes /health, /chat, /book, /saga/{id}, /chaos endpoints
  - Serves a rich single-page UI that shows both workers' health and saga progress

Start both workers (see scripts/start_workers.sh or start_workers.ps1):
    Worker A (us-west-2): WORKER_REGION=us-west-2 PEER_URL=http://localhost:8081
                          uvicorn src.api.server:app --port 8080
    Worker B (us-east-1): WORKER_REGION=us-east-1 PEER_URL=http://localhost:8080
                          uvicorn src.api.server:app --port 8081

Environment:
    WORKER_REGION     — this worker's region
    PEER_URL          — URL of the other worker (for UI health checks and chaos relay)
    PEER_REGION       — region label of the peer worker
    DSQL_ENDPOINT_A   — us-west-2 DSQL endpoint
    DSQL_ENDPOINT_B   — us-east-1 DSQL endpoint
"""
from __future__ import annotations

import json
import os
import uuid

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.db.dsql_client import get_connection
from src.db.chaos_store import is_region_disabled, disable_region, enable_region, get_all_regions
from src.db import saga_store
from src.agent.booking_agent import run_booking
from src.agent.loop import run_turn
from src.booking.models import BookingRequest


WORKER_REGION = os.environ.get("WORKER_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-west-2"))
PEER_URL      = os.environ.get("PEER_URL", "http://localhost:8081")
PEER_REGION   = os.environ.get("PEER_REGION", "us-east-1" if WORKER_REGION == "us-west-2" else "us-west-2")


def _endpoint_for_region(region: str) -> str:
    if region == os.environ.get("REGION_A", "us-west-2"):
        return os.environ.get("DSQL_ENDPOINT_A") or os.environ.get("DSQL_ENDPOINT", "")
    return os.environ.get("DSQL_ENDPOINT_B") or os.environ.get("DSQL_ENDPOINT_PEER", "")


def _conn():
    return get_connection(_endpoint_for_region(WORKER_REGION))


def _check_chaos(conn):
    if is_region_disabled(conn, WORKER_REGION):
        raise HTTPException(
            status_code=503,
            detail=f"Region {WORKER_REGION} is disabled by chaos flag. Route to peer region.",
        )


# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(title="ACME Booking Travel", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/response models ────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    input: str
    conversation_id: str | None = None
    user_id: str = "Workshop User"
    use_mock: bool = True


class BookRequest(BaseModel):
    saga_id: str | None = None
    conversation_id: str | None = None
    user_id: str
    origin: str
    destination: str
    date: str
    crash_after_step: str | None = None


class ChaosRequest(BaseModel):
    region: str
    reason: str = ""


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Health check — returns 503 if this region's chaos flag is set."""
    conn = _conn()
    try:
        _check_chaos(conn)
    finally:
        conn.close()
    return {"status": "ok", "region": WORKER_REGION}


@app.post("/chat")
def chat(req: ChatRequest):
    """Run one agent conversation turn. Persists everything to DSQL."""
    conn = _conn()
    try:
        _check_chaos(conn)
        conversation_id = req.conversation_id or str(uuid.uuid4())
        answer = run_turn(
            conn=conn,
            conversation_id=conversation_id,
            user_id=req.user_id,
            user_input=req.input,
            region=WORKER_REGION,
            use_mock=req.use_mock,
        )
        return {"conversation_id": conversation_id, "answer": answer, "region": WORKER_REGION}
    finally:
        conn.close()


@app.post("/book")
def book(req: BookRequest):
    """Run the full booking saga. Idempotent: supply the same saga_id to resume."""
    conn = _conn()
    try:
        _check_chaos(conn)

        saga_id = req.saga_id or str(uuid.uuid4())
        crash_injector = None
        if req.crash_after_step:
            from src.chaos.crash import CrashInjector
            crash_injector = CrashInjector(crash_after_step=req.crash_after_step)

        request = BookingRequest(
            saga_id=saga_id,
            conversation_id=req.conversation_id or str(uuid.uuid4()),
            user_id=req.user_id,
            origin=req.origin,
            destination=req.destination,
            date=req.date,
        )

        results = run_booking(
            request=request,
            endpoint=_endpoint_for_region(WORKER_REGION),
            region=WORKER_REGION,
            crash_injector=crash_injector,
        )
        return {"saga_id": saga_id, "region": WORKER_REGION, "results": results}
    finally:
        conn.close()


@app.get("/saga/{saga_id}")
def get_saga(saga_id: str):
    """Inspect the current state of a booking saga."""
    conn = _conn()
    try:
        saga = saga_store.get_saga(conn, saga_id)
        if not saga:
            raise HTTPException(status_code=404, detail=f"Saga {saga_id!r} not found")
        steps = saga_store.get_completed_step_names(conn, saga_id)
        return {"saga": saga, "completed_steps": steps}
    finally:
        conn.close()


# ── Chaos control ──────────────────────────────────────────────────────────────

@app.get("/chaos")
def get_chaos():
    """List chaos state for all regions."""
    conn = _conn()
    try:
        return {"regions": get_all_regions(conn)}
    finally:
        conn.close()


@app.post("/chaos/disable")
def chaos_disable(req: ChaosRequest):
    """Disable a regional worker (simulates outage). The peer region takes over."""
    conn = _conn()
    try:
        disable_region(conn, req.region, req.reason or "Disabled for workshop demo")
        return {"action": "disabled", "region": req.region}
    finally:
        conn.close()


@app.post("/chaos/enable")
def chaos_enable(req: ChaosRequest):
    """Re-enable a region."""
    conn = _conn()
    try:
        enable_region(conn, req.region)
        return {"action": "enabled", "region": req.region}
    finally:
        conn.close()


# ── Web UI ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def ui():
    """Rich SPA — polls both regional workers, visualizes saga steps, chaos controls."""
    config = {
        "selfRegion": WORKER_REGION,
        "selfUrl":    "",          # relative — this server
        "peerRegion": PEER_REGION,
        "peerUrl":    PEER_URL,
    }
    return HTMLResponse(_UI_TEMPLATE.replace("__CONFIG__", json.dumps(config)))


# ── HTML template ──────────────────────────────────────────────────────────────

_UI_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ACME Booking Travel — Durable Agent Demo</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Courier New',monospace;background:#0d1117;color:#c9d1d9;min-height:100vh}
a{color:#58a6ff}

/* Header */
.hdr{background:#161b22;border-bottom:1px solid #30363d;padding:14px 20px;display:flex;align-items:center;gap:12px}
.hdr h1{color:#58a6ff;font-size:1.15rem;white-space:nowrap}
.hdr .sub{color:#8b949e;font-size:0.8rem;margin-top:2px}
.badge{margin-left:auto;padding:4px 14px;border-radius:999px;font-size:0.78rem;font-weight:bold;white-space:nowrap}
.badge-ok{background:#1f6635;color:#56d364}
.badge-fail{background:#6e1a1a;color:#f85149}
.badge-warn{background:#3d2f00;color:#e3b341}

/* Layout */
.page{display:grid;grid-template-columns:260px 1fr 1fr;gap:14px;padding:14px;max-width:1380px;margin:0 auto}

/* Cards */
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}
.card h2{color:#8b949e;font-size:0.7rem;text-transform:uppercase;letter-spacing:.1em;margin-bottom:10px}
.col-left{grid-column:1}
.col-mid{grid-column:2}
.col-right{grid-column:3}
.col-full{grid-column:1/-1}
.col-span2{grid-column:2/4}

/* Inputs */
label{display:block;font-size:0.78rem;color:#8b949e;margin-bottom:3px}
input,select{width:100%;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:7px 9px;font-family:inherit;font-size:0.88rem;margin-bottom:10px}
input:focus,select:focus{outline:none;border-color:#58a6ff}
input[style*="text-transform"]{text-transform:uppercase}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:0 10px}

/* Buttons */
.btn{padding:7px 14px;border:none;border-radius:5px;cursor:pointer;font-family:inherit;font-size:0.88rem;font-weight:bold;transition:opacity .15s}
.btn:hover{opacity:.85}
.btn-primary{background:#238636;color:#fff}
.btn-danger{background:#da3633;color:#fff}
.btn-warn{background:#9e6a03;color:#fff}
.btn-ghost{background:#21262d;color:#c9d1d9}
.btn-sm{padding:5px 10px;font-size:0.78rem}
.btn-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}

/* Region cards */
.reg{display:flex;align-items:center;gap:10px;padding:10px;background:#0d1117;border:1px solid #30363d;border-radius:6px;margin-bottom:8px;transition:border-color .3s}
.reg.healthy{border-color:#238636}
.reg.dead{border-color:#da3633}
.dot{width:10px;height:10px;border-radius:50%;flex-shrink:0;transition:all .3s}
.dot-green{background:#56d364;box-shadow:0 0 6px #56d364}
.dot-red{background:#f85149;box-shadow:0 0 6px #f85149}
.dot-yellow{background:#e3b341;box-shadow:0 0 6px #e3b341}
.dot-gray{background:#6e7681}
.reg-name{font-size:.88rem;font-weight:bold}
.reg-status{font-size:.72rem;color:#8b949e;margin-top:2px}
.reg-tag{margin-left:auto}

/* Steps */
.step{display:flex;align-items:center;gap:10px;padding:10px 12px;background:#0d1117;border:1px solid #30363d;border-radius:6px;margin-bottom:6px;transition:all .4s}
.step.done{border-color:#238636;background:#0f2a18}
.step.running{border-color:#e3b341;background:#251d04;animation:pulse 1.2s infinite}
.step.failed{border-color:#da3633;background:#2a0f0f}
.step.idle{opacity:.45}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.65}}
.step-icon{font-size:1.1rem;width:22px;text-align:center;flex-shrink:0}
.step-name{font-size:.88rem;font-weight:bold}
.step-detail{font-size:.72rem;color:#8b949e;margin-top:1px}
.step-reg{font-size:.68rem;background:#30363d;color:#8b949e;padding:2px 6px;border-radius:3px;margin-left:4px;vertical-align:middle}

/* Tags */
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:.73rem;font-weight:bold}
.tag-green{background:#1f6635;color:#56d364}
.tag-red{background:#6e1a1a;color:#f85149}
.tag-yellow{background:#3d2f00;color:#e3b341}
.tag-blue{background:#0c2a62;color:#58a6ff}
.tag-gray{background:#21262d;color:#8b949e}

/* Log */
.log{height:180px;overflow-y:auto;background:#0d1117;border:1px solid #30363d;border-radius:5px;padding:8px;font-size:.76rem}
.log-line{padding:1px 0;border-bottom:1px solid #21262d}
.log-line:last-child{border-bottom:none}
.log-ts{color:#6e7681}
.c-ok{color:#56d364}.c-err{color:#f85149}.c-warn{color:#e3b341}.c-info{color:#58a6ff}.c-dim{color:#8b949e}

/* Booking result */
.result-box{background:#0d1117;border:1px solid #30363d;border-radius:5px;padding:10px;font-size:.76rem;white-space:pre-wrap;overflow:auto;max-height:160px;margin-top:8px}
.confirm-box{background:#0f2a18;border:1px solid #238636;border-radius:6px;padding:12px;margin-top:10px;display:none}
.confirm-box.show{display:block}
.confirm-box h3{color:#56d364;font-size:.88rem;margin-bottom:8px}
.kv{display:flex;justify-content:space-between;font-size:.78rem;margin-bottom:3px}
.kv-k{color:#8b949e}.kv-v{color:#c9d1d9}

hr{border:none;border-top:1px solid #30363d;margin:10px 0}
.small{font-size:.76rem;color:#8b949e}
</style>
</head>
<body>

<div class="hdr">
  <div>
    <h1>&#9992; ACME Booking Travel</h1>
    <div class="sub">Durable Agent Demo &mdash; Aurora DSQL Multi-Region</div>
  </div>
  <div id="routing-badge" class="badge badge-warn">Checking regions&hellip;</div>
</div>

<div class="page">

  <!-- LEFT COL: region health + chaos -->
  <div style="display:flex;flex-direction:column;gap:14px">

    <div class="card">
      <h2>Regional Agents</h2>
      <div id="reg-a" class="reg">
        <div id="dot-a" class="dot dot-gray"></div>
        <div>
          <div id="name-a" class="reg-name">us-west-2</div>
          <div id="status-a" class="reg-status">Checking&hellip;</div>
        </div>
        <div class="reg-tag" id="tag-a"></div>
      </div>
      <div id="reg-b" class="reg">
        <div id="dot-b" class="dot dot-gray"></div>
        <div>
          <div id="name-b" class="reg-name">us-east-1</div>
          <div id="status-b" class="reg-status">Checking&hellip;</div>
        </div>
        <div class="reg-tag" id="tag-b"></div>
      </div>
    </div>

    <div class="card">
      <h2>Chaos Control</h2>
      <div class="btn-row">
        <button class="btn btn-danger btn-sm" id="btn-kill-a" onclick="killRegion(C.selfRegion)">&#128165; Kill Oregon</button>
        <button class="btn btn-danger btn-sm" id="btn-kill-b" onclick="killRegion(C.peerRegion)">&#128165; Kill Virginia</button>
      </div>
      <div class="btn-row" style="margin-top:8px">
        <button class="btn btn-warn btn-sm" onclick="restoreAll()">&#9989; Restore All</button>
        <button class="btn btn-ghost btn-sm" onclick="pollHealth()">&#8635; Refresh</button>
      </div>
      <div id="chaos-msg" class="small" style="margin-top:8px"></div>
    </div>

    <div class="card">
      <h2>Quick Links</h2>
      <div class="small" style="line-height:1.8">
        <div><a href="/docs" target="_blank">API docs (this worker)</a></div>
        <div><a id="peer-docs" href="#" target="_blank">API docs (peer)</a></div>
        <div><a href="/chaos" target="_blank">GET /chaos (JSON)</a></div>
      </div>
    </div>
  </div>

  <!-- MIDDLE: Book a flight -->
  <div class="card">
    <h2>Book a Flight</h2>
    <div class="two-col">
      <div>
        <label>Origin</label>
        <input id="origin" value="SEA" maxlength="3" style="text-transform:uppercase">
      </div>
      <div>
        <label>Destination</label>
        <input id="dest" value="JFK" maxlength="3" style="text-transform:uppercase">
      </div>
    </div>
    <label>Date</label>
    <input id="date" value="2026-08-01">
    <label>User</label>
    <input id="user-id" value="Alice Workshop">
    <label>Saga ID &nbsp;<span class="c-dim">(blank = new booking; paste existing to resume)</span></label>
    <input id="saga-id-input" placeholder="leave blank to start a new saga">
    <label>Chaos: crash after step</label>
    <select id="crash">
      <option value="">No crash (run to completion)</option>
      <option value="hold_seat">Crash after hold_seat (step 1)</option>
      <option value="authorize_payment">Crash after authorize_payment (step 2)</option>
    </select>
    <label>Route to</label>
    <select id="route">
      <option value="auto">Auto &mdash; primary first, failover to peer on 503</option>
      <option value="self" id="opt-self">Primary only</option>
      <option value="peer" id="opt-peer">Peer only</option>
    </select>
    <div class="btn-row">
      <button class="btn btn-primary" onclick="bookFlight()">&#9992; Book Flight</button>
      <button class="btn btn-ghost btn-sm" onclick="clearSaga()">Clear</button>
    </div>
    <div id="confirm-box" class="confirm-box">
      <h3 id="confirm-title">Booking Result</h3>
      <div id="confirm-body"></div>
    </div>
  </div>

  <!-- RIGHT: Saga progress -->
  <div class="card">
    <h2>Saga Progress</h2>
    <div id="saga-label" class="small" style="margin-bottom:10px;word-break:break-all">No saga running</div>

    <div id="step-hold" class="step idle">
      <div class="step-icon">&#11036;</div>
      <div>
        <div class="step-name">1. hold_seat</div>
        <div id="detail-hold" class="step-detail">Reserve a seat on the flight</div>
      </div>
    </div>
    <div id="step-auth" class="step idle">
      <div class="step-icon">&#11036;</div>
      <div>
        <div class="step-name">2. authorize_payment</div>
        <div id="detail-auth" class="step-detail">Create booking with payment auth</div>
      </div>
    </div>
    <div id="step-confirm" class="step idle">
      <div class="step-icon">&#11036;</div>
      <div>
        <div class="step-name">3. confirm_booking</div>
        <div id="detail-confirm" class="step-detail">Capture payment &amp; confirm</div>
      </div>
    </div>

    <hr>
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
      <span id="saga-status-tag"></span>
      <span id="saga-region-chip" class="tag tag-gray" style="display:none"></span>
    </div>
    <div id="saga-meta" class="small"></div>

    <hr>
    <h2>DB Verify</h2>
    <div class="small" id="verify-sql" style="font-family:monospace;line-height:1.7;color:#58a6ff;word-break:break-all"></div>
  </div>

  <!-- BOTTOM: Activity log -->
  <div class="card col-full">
    <h2>Activity Log</h2>
    <div id="log" class="log"></div>
  </div>
</div>

<script>
const C = __CONFIG__;

let currentSagaId = null;
let sagaTimer = null;
let healthTimer = null;

// ── Logging ───────────────────────────────────────────────────────────────────
function ts() { return new Date().toTimeString().slice(0,8); }
function log(msg, cls='') {
  const el = document.getElementById('log');
  const d = document.createElement('div');
  d.className = 'log-line';
  d.innerHTML = `<span class="log-ts">[${ts()}]</span> <span class="${cls}">${msg}</span>`;
  el.prepend(d);
  while (el.children.length > 120) el.removeChild(el.lastChild);
}

// ── Fetch helper ──────────────────────────────────────────────────────────────
async function apiFetch(url, opts) {
  try {
    const r = await fetch(url, opts);
    let data = {};
    try { data = await r.json(); } catch(_) {}
    return { ok: r.ok, status: r.status, data };
  } catch(e) {
    return { ok: false, status: 0, data: {}, err: String(e) };
  }
}

function peerUrl(path) { return C.peerUrl + path; }

// ── Health polling ─────────────────────────────────────────────────────────────
async function pollHealth() {
  const [ra, rb] = await Promise.all([
    apiFetch('/health'),
    apiFetch(peerUrl('/health')),
  ]);

  function applyCard(prefix, result, region, isPrimary) {
    const regEl  = document.getElementById('reg-' + prefix);
    const dotEl  = document.getElementById('dot-' + prefix);
    const statEl = document.getElementById('status-' + prefix);
    const tagEl  = document.getElementById('tag-' + prefix);
    if (result.ok) {
      dotEl.className = 'dot dot-green';
      regEl.className = 'reg healthy';
      statEl.textContent = 'Healthy';
      tagEl.innerHTML = '<span class="tag tag-green">UP</span>';
    } else if (result.status === 503) {
      dotEl.className = 'dot dot-red';
      regEl.className = 'reg dead';
      statEl.textContent = 'DISABLED — chaos flag set';
      tagEl.innerHTML = '<span class="tag tag-red">DOWN</span>';
    } else {
      dotEl.className = 'dot dot-yellow';
      regEl.className = 'reg';
      statEl.textContent = result.status === 0 ? 'Unreachable' : `HTTP ${result.status}`;
      tagEl.innerHTML = '<span class="tag tag-yellow">??</span>';
    }
  }

  applyCard('a', ra, C.selfRegion, true);
  applyCard('b', rb, C.peerRegion, false);

  const badge = document.getElementById('routing-badge');
  if (ra.ok) {
    badge.textContent = `Active: ${C.selfRegion} (primary)`;
    badge.className = 'badge badge-ok';
  } else if (rb.ok) {
    badge.textContent = `Active: ${C.peerRegion} (failover — primary DOWN)`;
    badge.className = 'badge badge-fail';
  } else {
    badge.textContent = 'No healthy region';
    badge.className = 'badge badge-warn';
  }
}

// ── Booking ───────────────────────────────────────────────────────────────────
async function bookFlight() {
  const origin   = document.getElementById('origin').value.toUpperCase();
  const dest     = document.getElementById('dest').value.toUpperCase();
  const date     = document.getElementById('date').value;
  const userId   = document.getElementById('user-id').value;
  const sagaIn   = document.getElementById('saga-id-input').value.trim();
  const crash    = document.getElementById('crash').value || null;
  const routePref= document.getElementById('route').value;

  const body = { user_id: userId, origin, destination: dest, date, crash_after_step: crash };
  if (sagaIn) body.saga_id = sagaIn;

  log(`Booking ${origin}&#x2192;${dest} on ${date}${crash ? ' [crash after ' + crash + ']' : ''}`, 'c-info');

  const targets = routePref === 'peer'  ? ['peer'] :
                  routePref === 'self'  ? ['self'] :
                  ['self', 'peer'];

  let result = null, usedRegion = null;
  for (const t of targets) {
    const url    = t === 'peer' ? peerUrl('/book') : '/book';
    const region = t === 'peer' ? C.peerRegion : C.selfRegion;
    log(`&#10132; Sending to ${region} (${url})&hellip;`, 'c-dim');

    const { ok, status, data } = await apiFetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (ok) {
      result = data; usedRegion = region;
      log(`&#10003; Accepted by ${region}`, 'c-ok');
      break;
    }
    if (status === 503) {
      log(`&#10007; ${region} returned 503 (chaos — disabled). ${targets.includes('peer') && t === 'self' ? 'Failing over&hellip;' : ''}`, 'c-warn');
      // Pass saga_id so peer can resume
      if (data.saga_id) body.saga_id = data.saga_id;
    } else {
      log(`&#10007; ${region} error ${status}: ${JSON.stringify(data)}`, 'c-err');
    }
  }

  if (!result) { log('Booking failed — all regions exhausted', 'c-err'); return; }

  currentSagaId = result.saga_id;
  document.getElementById('saga-id-input').value = result.saga_id;
  document.getElementById('saga-label').innerHTML =
    `Saga: <span style="color:#58a6ff">${result.saga_id}</span>`;

  showVerifySQL(result.saga_id);
  renderConfirm(result, usedRegion);
  startSagaPoll();
  pollHealth();
}

function renderConfirm(data, region) {
  const box   = document.getElementById('confirm-box');
  const title = document.getElementById('confirm-title');
  const body  = document.getElementById('confirm-body');
  const r     = data.results || {};
  const hold  = r.hold_seat           || {};
  const auth  = r.authorize_payment   || {};
  const conf  = r.confirm_booking     || {};
  const done  = conf.status === 'confirmed';

  box.className = 'confirm-box show';
  title.textContent = done ? '✅ Booking Confirmed' : '⏳ Saga In Progress';
  title.style.color = done ? '#56d364' : '#e3b341';
  body.innerHTML = [
    kv('Region', region),
    kv('Saga ID', data.saga_id || '—'),
    kv('Flight hold', hold.hold_id ? hold.hold_id.slice(0,18)+'…' : '—'),
    kv('Seat', hold.seat_number || '—'),
    kv('Booking ID', conf.booking_id || auth.booking_id || '—'),
    kv('Status', conf.status || auth.status || 'in_progress'),
  ].join('');
}

function kv(k, v) {
  return `<div class="kv"><span class="kv-k">${k}</span><span class="kv-v">${v}</span></div>`;
}

// ── Saga progress polling ─────────────────────────────────────────────────────
function startSagaPoll() {
  if (sagaTimer) clearInterval(sagaTimer);
  sagaTimer = setInterval(pollSaga, 1800);
  pollSaga();
}

async function pollSaga() {
  if (!currentSagaId) return;
  let saga = null;
  for (const base of ['', C.peerUrl]) {
    const { ok, data } = await apiFetch(base + '/saga/' + currentSagaId);
    if (ok && data.saga) { saga = data; break; }
  }
  if (!saga) return;

  const { status, current_step, last_touched_region } = saga.saga;
  const done = new Set(saga.completed_steps || []);

  const steps = [
    { id:'step-hold',    key:'hold_seat',          detail:'Reserve a seat on the flight' },
    { id:'step-auth',    key:'authorize_payment',   detail:'Create booking with payment auth' },
    { id:'step-confirm', key:'confirm_booking',     detail:'Capture payment &amp; confirm' },
  ];

  let foundActive = false;
  for (const s of steps) {
    const el   = document.getElementById(s.id);
    const icon = el.querySelector('.step-icon');
    const det  = el.querySelector('.step-detail');
    if (done.has(s.key)) {
      el.className = 'step done';
      icon.textContent = '✅';
      det.innerHTML = `Completed <span class="step-reg">${last_touched_region || ''}</span>`;
    } else if (!foundActive && status === 'in_progress') {
      el.className = 'step running';
      icon.textContent = '⏳';
      det.innerHTML = `Running&hellip; <span class="step-reg">${last_touched_region || ''}</span>`;
      foundActive = true;
    } else if (status === 'failed' && !foundActive) {
      el.className = 'step failed';
      icon.textContent = '❌';
      det.textContent = 'Failed';
      foundActive = true;
    } else {
      el.className = 'step idle';
      icon.textContent = '⬜';
      det.innerHTML = s.detail;
    }
  }

  const stag = document.getElementById('saga-status-tag');
  const chip = document.getElementById('saga-region-chip');
  chip.style.display = 'inline-block';
  chip.textContent = last_touched_region || '';

  if (status === 'completed') {
    stag.innerHTML = '<span class="tag tag-green">COMPLETED</span>';
    clearInterval(sagaTimer);
  } else if (status === 'failed') {
    stag.innerHTML = '<span class="tag tag-red">FAILED</span>';
    clearInterval(sagaTimer);
  } else {
    stag.innerHTML = '<span class="tag tag-yellow">IN PROGRESS</span>';
  }

  document.getElementById('saga-meta').textContent =
    `Step ${current_step}/3 · last touched ${last_touched_region || '?'}`;
}

// ── Chaos ─────────────────────────────────────────────────────────────────────
async function killRegion(region) {
  log(`&#128165; Killing region ${region}&hellip;`, 'c-warn');
  const msg = document.getElementById('chaos-msg');
  const body = JSON.stringify({ region, reason: 'Workshop demo kill-switch' });
  const hdrs = { 'Content-Type': 'application/json' };
  // Try both workers so either can write the flag
  let done = false;
  for (const base of ['', C.peerUrl]) {
    const { ok } = await apiFetch(base + '/chaos/disable', { method:'POST', headers:hdrs, body });
    if (ok) { done = true; break; }
  }
  if (done) {
    log(`&#10003; ${region} chaos flag set`, 'c-warn');
    msg.innerHTML = `<span class="c-warn">&#10003; ${region} disabled</span>`;
  } else {
    log(`&#10007; Could not disable ${region}`, 'c-err');
  }
  pollHealth();
}

async function restoreAll() {
  log('Restoring all regions&hellip;', 'c-info');
  const hdrs = { 'Content-Type': 'application/json' };
  for (const region of [C.selfRegion, C.peerRegion]) {
    for (const base of ['', C.peerUrl]) {
      const { ok } = await apiFetch(base + '/chaos/enable', {
        method:'POST', headers:hdrs,
        body: JSON.stringify({ region }),
      });
      if (ok) break;
    }
  }
  log('All regions restored', 'c-ok');
  document.getElementById('chaos-msg').innerHTML = '';
  pollHealth();
}

// ── SQL snippet for DB verification ──────────────────────────────────────────
function showVerifySQL(sagaId) {
  document.getElementById('verify-sql').innerHTML = [
    `-- Saga state:`,
    `SELECT status, current_step, last_touched_region`,
    `FROM sagas WHERE saga_id='${sagaId}'::uuid;`,
    ``,
    `-- Completed steps:`,
    `SELECT step_index, step_name, direction, status`,
    `FROM saga_steps WHERE saga_id='${sagaId}'::uuid`,
    `ORDER BY step_index;`,
  ].map(l => l ? l : '&nbsp;').join('<br>');
}

function clearSaga() {
  currentSagaId = null;
  if (sagaTimer) clearInterval(sagaTimer);
  document.getElementById('saga-id-input').value = '';
  document.getElementById('saga-label').textContent = 'No saga running';
  document.getElementById('saga-status-tag').innerHTML = '';
  document.getElementById('saga-region-chip').style.display = 'none';
  document.getElementById('saga-meta').textContent = '';
  document.getElementById('confirm-box').className = 'confirm-box';
  document.getElementById('verify-sql').textContent = '';
  for (const [id, detail] of [
    ['step-hold',    'Reserve a seat on the flight'],
    ['step-auth',    'Create booking with payment auth'],
    ['step-confirm', 'Capture payment & confirm'],
  ]) {
    const el = document.getElementById(id);
    el.className = 'step idle';
    el.querySelector('.step-icon').textContent = '⬜';
    el.querySelector('.step-detail').textContent = detail;
  }
  log('Saga state cleared', 'c-dim');
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.getElementById('opt-self').textContent = `Primary only (${C.selfRegion})`;
document.getElementById('opt-peer').textContent = `Peer only (${C.peerRegion})`;
document.getElementById('btn-kill-a').textContent = `\u{1F4A5} Kill ${C.selfRegion}`;
document.getElementById('btn-kill-b').textContent = `\u{1F4A5} Kill ${C.peerRegion}`;
document.getElementById('peer-docs').href = C.peerUrl + '/docs';

pollHealth();
healthTimer = setInterval(pollHealth, 3000);
log(`UI ready · self=${C.selfRegion} · peer=${C.peerRegion} (${C.peerUrl})`, 'c-info');
</script>
</body>
</html>"""
