"""
common.py — shared data + indicator layer for the edge scanner suite.

Data provider is pluggable. Default uses yfinance (free, fine for daily-bar
scanning). For options chains with real greeks/IV, swap in Tradier or Polygon
by implementing the same two functions. Designed to run on darth-rawsejet
alongside the existing TimescaleDB stack — persist hooks are at the bottom.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf

# ----------------------------------------------------------------------------
# Data access — delegates to Tradier (real-time, real greeks) when
# TRADIER_TOKEN is set; falls back to yfinance otherwise.
# ----------------------------------------------------------------------------

import os

_USE_TRADIER = bool(os.environ.get("TRADIER_TOKEN"))
if _USE_TRADIER:
    import tradier_data


def get_daily_bars(ticker: str, lookback_days: int = 400) -> pd.DataFrame:
    """Daily OHLCV. Returns a DataFrame indexed by date with columns
    open/high/low/close/volume. Empty DataFrame on failure."""
    if _USE_TRADIER:
        try:
            return tradier_data.get_daily_bars(ticker, lookback_days)
        except Exception:
            return pd.DataFrame()
    try:
        df = yf.Ticker(ticker).history(period=f"{lookback_days}d", auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        return df.dropna()
    except Exception:
        return pd.DataFrame()


def get_option_chain(ticker: str, max_dte: int = 60) -> pd.DataFrame:
    """Puts and calls within max_dte. Columns: type, strike, dte, bid, ask,
    mid, iv, oi, volume, expiry. With TRADIER_TOKEN set you also get real
    delta/gamma/theta/vega and occ_symbol; yfinance IV is approximate."""
    if _USE_TRADIER:
        try:
            return tradier_data.get_option_chain(ticker, max_dte)
        except Exception:
            return pd.DataFrame()
    rows = []
    try:
        tk = yf.Ticker(ticker)
        today = datetime.now(timezone.utc).date()
        for exp in tk.options:
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if dte <= 0 or dte > max_dte:
                continue
            chain = tk.option_chain(exp)
            for opt_type, frame in (("put", chain.puts), ("call", chain.calls)):
                for _, r in frame.iterrows():
                    bid, ask = float(r.get("bid") or 0), float(r.get("ask") or 0)
                    if bid <= 0 or ask <= 0:
                        continue
                    rows.append({
                        "type": opt_type,
                        "strike": float(r["strike"]),
                        "dte": dte,
                        "bid": bid,
                        "ask": ask,
                        "mid": (bid + ask) / 2,
                        "spread_pct": (ask - bid) / ((bid + ask) / 2),
                        "iv": float(r.get("impliedVolatility") or 0),
                        "oi": int(r.get("openInterest") or 0),
                        "volume": int(r.get("volume") or 0),
                        "expiry": exp,
                    })
    except Exception:
        pass
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# Indicators
# ----------------------------------------------------------------------------

def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    plus_dm = (h.diff()).where((h.diff() > l.diff().abs()) & (h.diff() > 0), 0.0)
    minus_dm = (-l.diff()).where(((-l.diff()) > h.diff()) & (l.diff() < 0), 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def realized_vol(close: pd.Series, n: int = 20) -> float:
    """Annualized close-to-close realized vol over the last n days."""
    rets = np.log(close / close.shift(1)).dropna().tail(n)
    if len(rets) < n // 2:
        return float("nan")
    return float(rets.std() * math.sqrt(252))


def zscore(s: pd.Series, n: int = 20) -> pd.Series:
    m, sd = s.rolling(n).mean(), s.rolling(n).std()
    return (s - m) / sd


def put_delta_approx(spot: float, strike: float, iv: float, dte: int, r: float = 0.05) -> float:
    """Black-Scholes put delta (negative). Good enough for filtering."""
    t = max(dte, 1) / 365
    if iv <= 0 or spot <= 0 or strike <= 0:
        return float("nan")
    d1 = (math.log(spot / strike) + (r + iv**2 / 2) * t) / (iv * math.sqrt(t))
    # N(d1) via erf
    nd1 = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
    return nd1 - 1.0


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------

@dataclass
class Signal:
    scanner: str
    ticker: str
    headline: str
    details: dict = field(default_factory=dict)

    def fmt(self) -> str:
        kv = " | ".join(f"{k}={v}" for k, v in self.details.items())
        return f"[{self.scanner}] {self.ticker}: {self.headline} ({kv})"


def emit(signals: list[Signal], discord_webhook: str | None = None) -> None:
    """Print signals; optionally push to Discord (same webhook pattern as the
    ANALYST watchlist alerts)."""
    for s in signals:
        print(s.fmt())
    if discord_webhook and signals:
        try:
            import requests
            body = "\n".join(s.fmt() for s in signals)[:1900]
            requests.post(discord_webhook, json={"content": f"```\n{body}\n```"}, timeout=10)
        except Exception as e:
            print(f"discord push failed: {e}")
