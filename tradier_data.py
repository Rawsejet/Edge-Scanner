"""
tradier_data.py — real-time market data adapter (Tradier brokerage API).

Drop-in replacement for the yfinance functions in common.py, with two big
upgrades for the premium scanner:
  - real greeks and IV (ORATS-sourced) instead of Black-Scholes approximations
  - real-time quotes instead of delayed bars

Setup:
  export TRADIER_TOKEN="..."          # production token = real-time data
  export TRADIER_ENV="prod"           # or "sandbox" for delayed/paper data

READ-ONLY by design. This module only touches /v1/markets/* endpoints.
No account, no orders, no write scope — execution stays manual in Fidelity.
The option symbols returned (OCC format, e.g. ASTS260612P00040000) identify
the exact same contracts you'll see in Fidelity's chain.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

_BASE = {
    "prod": "https://api.tradier.com/v1",
    "sandbox": "https://sandbox.tradier.com/v1",
}


def _get(path: str, params: dict) -> dict:
    env = os.environ.get("TRADIER_ENV", "prod")
    token = os.environ.get("TRADIER_TOKEN")
    if not token:
        raise RuntimeError("TRADIER_TOKEN not set")
    r = requests.get(
        f"{_BASE[env]}{path}",
        params=params,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def get_quote(symbols: list[str]) -> pd.DataFrame:
    """Real-time quotes. Columns: symbol, last, bid, ask, change_pct, volume."""
    data = _get("/markets/quotes", {"symbols": ",".join(symbols)})
    q = data.get("quotes", {}).get("quote", [])
    if isinstance(q, dict):
        q = [q]
    rows = [{
        "symbol": x.get("symbol"),
        "last": x.get("last"),
        "bid": x.get("bid"),
        "ask": x.get("ask"),
        "change_pct": x.get("change_percentage"),
        "volume": x.get("volume"),
    } for x in q]
    return pd.DataFrame(rows)


def get_daily_bars(ticker: str, lookback_days: int = 400) -> pd.DataFrame:
    """Daily OHLCV — same shape as common.get_daily_bars."""
    start = (datetime.now(timezone.utc) - timedelta(days=int(lookback_days * 1.5))).date()
    data = _get("/markets/history", {
        "symbol": ticker, "interval": "daily",
        "start": start.isoformat(),
        "end": datetime.now(timezone.utc).date().isoformat(),
    })
    days = (data.get("history") or {}).get("day", [])
    if isinstance(days, dict):
        days = [days]
    if not days:
        return pd.DataFrame()
    df = pd.DataFrame(days)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")[["open", "high", "low", "close", "volume"]].astype(float)
    return df.dropna().tail(lookback_days)


def get_option_chain(ticker: str, max_dte: int = 60) -> pd.DataFrame:
    """Chains with REAL greeks/IV. Same columns as common.get_option_chain,
    plus: delta, gamma, theta, vega, occ_symbol."""
    today = datetime.now(timezone.utc).date()
    exps = _get("/markets/options/expirations", {"symbol": ticker})
    dates = (exps.get("expirations") or {}).get("date", [])
    if isinstance(dates, str):
        dates = [dates]

    rows = []
    for exp in dates:
        dte = (datetime.strptime(exp, "%Y-%m-%d").date() - today).days
        if dte <= 0 or dte > max_dte:
            continue
        chain = _get("/markets/options/chains",
                     {"symbol": ticker, "expiration": exp, "greeks": "true"})
        opts = (chain.get("options") or {}).get("option", [])
        if isinstance(opts, dict):
            opts = [opts]
        for o in opts:
            bid, ask = float(o.get("bid") or 0), float(o.get("ask") or 0)
            if bid <= 0 or ask <= 0:
                continue
            g = o.get("greeks") or {}
            mid = (bid + ask) / 2
            rows.append({
                "type": o.get("option_type"),
                "strike": float(o.get("strike")),
                "dte": dte,
                "bid": bid, "ask": ask, "mid": mid,
                "spread_pct": (ask - bid) / mid,
                "iv": float(g.get("mid_iv") or g.get("smv_vol") or 0),
                "delta": float(g.get("delta") or 0),
                "gamma": float(g.get("gamma") or 0),
                "theta": float(g.get("theta") or 0),
                "vega": float(g.get("vega") or 0),
                "oi": int(o.get("open_interest") or 0),
                "volume": int(o.get("volume") or 0),
                "expiry": exp,
                "occ_symbol": o.get("symbol"),  # paste-matches Fidelity's chain
            })
    return pd.DataFrame(rows)
