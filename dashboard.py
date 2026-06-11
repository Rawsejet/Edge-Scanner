"""
dashboard.py — live signal board for the edge scanner suite.

Runs the four scanners on an interval and streams results to the browser over
WebSocket. Read-only end to end: market data in, signals out, orders placed by
a human in Fidelity. The occ_symbol on premium signals identifies the exact
contract to pull up in Fidelity's chain.

Run on darth-rawsejet:
    pip install fastapi uvicorn requests pandas numpy yfinance
    export TRADIER_TOKEN="..."            # real-time data + real greeks
    uvicorn dashboard:app --host 0.0.0.0 --port 8787
Then open http://darth-rawsejet:8787

Intervals: full chain scans are heavy (one request per ticker per expiry), so
the default is a full scan every 5 minutes and a quote-rail refresh every 15s.
Cranking SCAN_INTERVAL below ~120s mostly buys rate-limit errors, not edge —
none of these strategies decay on a seconds timescale.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

import scanner_meanreversion
import scanner_momentum
import scanner_premium
from run_all import UNIVERSE

SCAN_INTERVAL = int(os.environ.get("SCAN_INTERVAL", 300))   # seconds
QUOTE_INTERVAL = int(os.environ.get("QUOTE_INTERVAL", 15))  # seconds

app = FastAPI()
clients: set[WebSocket] = set()
state: dict = {"signals": [], "regime": {}, "quotes": [], "last_scan": None}

# --- Prometheus metrics (scraped by the mini PC's local Prometheus) ---------
from prometheus_client import (CONTENT_TYPE_LATEST, Counter, Gauge, Histogram,
                               generate_latest)
from fastapi.responses import Response

M_SIGNALS = Gauge("scanner_signals", "Signals in last scan", ["scanner"])
M_REGIME = Gauge("scanner_regime_on", "1 if scanner regime allows trading", ["scanner"])
M_SCAN_SECS = Histogram("scanner_scan_duration_seconds", "Full scan wall time",
                        buckets=(5, 15, 30, 60, 120, 300, 600))
M_SCAN_ERRORS = Counter("scanner_errors_total", "Scanner exceptions", ["scanner"])
M_LAST_SCAN = Gauge("scanner_last_scan_timestamp", "Unix time of last completed scan")


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def broadcast(msg: dict) -> None:
    dead = []
    for ws in clients:
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


def run_scans() -> dict:
    import time
    t0 = time.time()
    sigs = []
    for mod, name in ((scanner_premium, "PREMIUM"),
                      (scanner_momentum, "MOMENTUM"),
                      (scanner_meanreversion, "MEANREV")):
        try:
            for s in mod.scan(UNIVERSE):
                sigs.append({"scanner": s.scanner, "ticker": s.ticker,
                             "headline": s.headline, "details": s.details})
        except Exception as e:
            M_SCAN_ERRORS.labels(scanner=name).inc()
            sigs.append({"scanner": name, "ticker": "—",
                         "headline": f"scanner error: {e}", "details": {}})
    regime = {
        "momentum_on": scanner_momentum.check_regime(),
        "meanrev_on": scanner_meanreversion.crash_guard(),
    }
    for name in ("PREMIUM", "MOMENTUM", "MEANREV"):
        M_SIGNALS.labels(scanner=name).set(
            sum(1 for s in sigs if s["scanner"] == name))
    M_REGIME.labels(scanner="MOMENTUM").set(int(regime["momentum_on"]))
    M_REGIME.labels(scanner="MEANREV").set(int(regime["meanrev_on"]))
    M_SCAN_SECS.observe(time.time() - t0)
    M_LAST_SCAN.set(time.time())
    return {"signals": sigs, "regime": regime,
            "last_scan": datetime.now(timezone.utc).strftime("%H:%M:%S UTC")}


def get_quotes() -> list[dict]:
    if not os.environ.get("TRADIER_TOKEN"):
        return []
    try:
        import tradier_data
        df = tradier_data.get_quote(UNIVERSE)
        return df.to_dict("records")
    except Exception:
        return []


async def scan_loop() -> None:
    loop = asyncio.get_event_loop()
    while True:
        result = await loop.run_in_executor(None, run_scans)
        state.update(result)
        await broadcast({"type": "scan", **result})
        await asyncio.sleep(SCAN_INTERVAL)


async def quote_loop() -> None:
    loop = asyncio.get_event_loop()
    while True:
        quotes = await loop.run_in_executor(None, get_quotes)
        if quotes:
            state["quotes"] = quotes
            await broadcast({"type": "quotes", "quotes": quotes})
        await asyncio.sleep(QUOTE_INTERVAL)


@app.on_event("startup")
async def startup() -> None:
    asyncio.create_task(scan_loop())
    asyncio.create_task(quote_loop())


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    clients.add(ws)
    await ws.send_text(json.dumps({"type": "scan", **{k: state[k] for k in
                                   ("signals", "regime", "last_scan")}}))
    if state["quotes"]:
        await ws.send_text(json.dumps({"type": "quotes", "quotes": state["quotes"]}))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(PAGE)


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Signal Board</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;800&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>
  :root{
    --ink:#0B0E14; --panel:#11151D; --line:#1D232E; --text:#C8D0DC; --dim:#5C6878;
    --premium:#E8B44C; --momentum:#3FD0A8; --meanrev:#9D8CFF; --down:#E0566B;
  }
  *{box-sizing:border-box;margin:0}
  body{background:var(--ink);color:var(--text);font:14px/1.5 'JetBrains Mono',monospace}
  header{display:flex;align-items:baseline;gap:16px;padding:14px 20px;border-bottom:1px solid var(--line)}
  header h1{font:600 13px 'Inter',sans-serif;letter-spacing:.18em;text-transform:uppercase;color:var(--dim)}
  #lastscan{margin-left:auto;color:var(--dim);font-size:12px}
  /* regime rail — the board's spine: scanners that are OFF say so loudly */
  #rail{display:flex;gap:0;border-bottom:1px solid var(--line)}
  .regime{flex:1;padding:10px 20px;font-size:12px;border-right:1px solid var(--line)}
  .regime b{display:block;font-weight:800;font-size:15px;margin-top:2px}
  .on b{color:var(--momentum)} .off b{color:var(--down)}
  /* quote tape */
  #tape{display:flex;gap:26px;overflow-x:auto;padding:8px 20px;border-bottom:1px solid var(--line);font-size:12px;white-space:nowrap}
  #tape .up{color:var(--momentum)} #tape .dn{color:var(--down)}
  /* signal feed */
  main{padding:18px 20px;max-width:1080px}
  .sig{display:grid;grid-template-columns:96px 72px 1fr;gap:14px;padding:11px 0;border-bottom:1px solid var(--line);align-items:baseline}
  .tag{font-weight:800;font-size:11px;letter-spacing:.1em}
  .PREMIUM{color:var(--premium)} .MOMENTUM{color:var(--momentum)} .MEANREV{color:var(--meanrev)}
  .tkr{font-weight:600}
  .sig small{display:block;color:var(--dim);margin-top:2px}
  #empty{color:var(--dim);padding:40px 0;font-size:13px}
  footer{padding:14px 20px;color:var(--dim);font-size:11px;border-top:1px solid var(--line)}
  @media(max-width:640px){.sig{grid-template-columns:80px 1fr};.sig .tkr{grid-column:2}}
</style></head><body>
<header><h1>Edge Scanner — Signal Board</h1><span id="lastscan">connecting…</span></header>
<div id="rail">
  <div class="regime" id="r-mom">MOMENTUM REGIME (SPY &gt; 200SMA)<b>—</b></div>
  <div class="regime" id="r-mr">MEANREV CRASH GUARD<b>—</b></div>
</div>
<div id="tape"></div>
<main><div id="feed"><div id="empty">Waiting for first scan… no signals is a valid output.</div></div></main>
<footer>Read-only signal feed. Orders are placed manually in your brokerage — verify earnings flags and news before acting on anything here.</footer>
<script>
  const feed = document.getElementById('feed');
  function render(signals){
    if(!signals.length){feed.innerHTML='<div id="empty">No signals this scan. Forcing trades on no-signal days is where edges go to die.</div>';return}
    feed.innerHTML = signals.map(s=>{
      const kv = Object.entries(s.details).map(([k,v])=>k+'='+v).join(' · ');
      return `<div class="sig"><span class="tag ${s.scanner}">${s.scanner}</span>`+
             `<span class="tkr">${s.ticker}</span><span>${s.headline}<small>${kv}</small></span></div>`;
    }).join('');
  }
  function regime(r){
    const m=document.querySelector('#r-mom b'), g=document.querySelector('#r-mr b');
    m.textContent = r.momentum_on ? 'RISK-ON' : 'STANDING DOWN';
    g.textContent = r.meanrev_on ? 'CLEAR' : 'GUARD ACTIVE';
    document.getElementById('r-mom').className='regime '+(r.momentum_on?'on':'off');
    document.getElementById('r-mr').className='regime '+(r.meanrev_on?'on':'off');
  }
  function tape(quotes){
    document.getElementById('tape').innerHTML = quotes.map(q=>{
      const c=(q.change_pct??0), cls=c>=0?'up':'dn', sign=c>=0?'+':'';
      return `<span><b>${q.symbol}</b> ${q.last??'—'} <span class="${cls}">${sign}${(c).toFixed(2)}%</span></span>`;
    }).join('');
  }
  function connect(){
    const ws = new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
    ws.onmessage = e=>{
      const m = JSON.parse(e.data);
      if(m.type==='scan'){render(m.signals||[]);regime(m.regime||{});
        document.getElementById('lastscan').textContent='last scan '+(m.last_scan||'—');}
      if(m.type==='quotes') tape(m.quotes||[]);
    };
    ws.onclose = ()=>setTimeout(connect, 3000);
  }
  connect();
</script></body></html>"""
