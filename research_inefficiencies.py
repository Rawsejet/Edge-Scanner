"""
research_inefficiencies.py — hypothesis-testing harness for structural edges.

Honest framing: there is no "scanner" for undiscovered inefficiencies. What
exists is a PROCESS — state a hypothesis, test it on history with realistic
costs, check stability across time, and assume decay once it's crowded. This
module is that process in code, with two worked examples you can clone:

  1. Overnight vs intraday return split — a documented structural pattern
     where a large share of equity returns accrue close-to-open rather than
     open-to-close, varying widely by ticker.
  2. Post-earnings announcement drift (PEAD) skeleton — stocks gapping hard
     on earnings tend to continue drifting in the gap direction for days/weeks.

How to use this for NEW ideas:
  - Write the hypothesis as a sentence with a falsifiable claim.
  - Implement it as a Study subclass returning per-trade returns.
  - Judge it on: mean per-trade edge AFTER costs, hit rate, t-stat, and
    stability across yearly subperiods. An edge that exists only in 2021
    is a backtest artifact, not an edge.
  - COSTS_BPS below is round-trip friction. If the edge dies when you set
    costs realistically, the edge was never yours — it belonged to the spread.

Decay check: re-run quarterly. Real structural edges shrink as they get
arbitraged; track the per-year mean and retire the strategy when it converges
to zero. That discipline is the actual moat, not the idea itself.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import get_daily_bars

COSTS_BPS = 5  # round-trip cost assumption in basis points; be pessimistic


def _summary(rets: pd.Series, label: str) -> dict:
    rets = rets.dropna()
    if len(rets) < 30:
        return {"label": label, "n": len(rets), "verdict": "insufficient data"}
    net = rets - COSTS_BPS / 10_000
    t_stat = float(net.mean() / (net.std() / np.sqrt(len(net))))
    yearly = net.groupby(net.index.year).mean()
    return {
        "label": label,
        "n": int(len(net)),
        "mean_bps_after_cost": round(float(net.mean()) * 10_000, 2),
        "hit_rate": round(float((net > 0).mean()), 3),
        "t_stat": round(t_stat, 2),
        "yearly_mean_bps": {int(y): round(v * 10_000, 1) for y, v in yearly.items()},
        "verdict": ("worth paper-trading" if t_stat > 2 and float(net.mean()) > 0
                    else "no exploitable edge after costs"),
    }


# ----------------------------------------------------------------------------
# Study 1: overnight vs intraday split
# ----------------------------------------------------------------------------

def study_overnight_split(ticker: str, lookback_days: int = 750) -> dict:
    """Hypothesis: for <ticker>, close->open returns differ structurally from
    open->close returns. If overnight dominates after costs, holding overnight
    and exiting at open captures it (tax/fill realities apply)."""
    df = get_daily_bars(ticker, lookback_days)
    if df.empty or len(df) < 100:
        return {"label": f"overnight {ticker}", "verdict": "no data"}
    overnight = df["open"] / df["close"].shift(1) - 1
    intraday = df["close"] / df["open"] - 1
    return {
        "ticker": ticker,
        "overnight": _summary(overnight, f"{ticker} close->open"),
        "intraday": _summary(intraday, f"{ticker} open->close"),
    }


# ----------------------------------------------------------------------------
# Study 2: post-earnings drift skeleton
# ----------------------------------------------------------------------------

def study_pead(ticker: str, gap_threshold: float = 0.05,
               hold_days: int = 10, lookback_days: int = 750) -> dict:
    """Hypothesis: a >5% overnight gap (earnings proxy) continues drifting in
    the gap direction over the next 10 sessions. Proper version uses actual
    earnings dates + surprise magnitude from a fundamentals API; the gap proxy
    is the zero-dependency starting point."""
    df = get_daily_bars(ticker, lookback_days)
    if df.empty or len(df) < 100:
        return {"label": f"pead {ticker}", "verdict": "no data"}
    gap = df["open"] / df["close"].shift(1) - 1
    events = gap[gap.abs() >= gap_threshold]
    rows = []
    closes = df["close"]
    for dt, g in events.items():
        idx = df.index.get_loc(dt)
        if idx + hold_days >= len(df):
            continue
        fwd = closes.iloc[idx + hold_days] / df["open"].iloc[idx] - 1
        rows.append((dt, np.sign(g) * fwd))   # trade WITH the gap direction
    if not rows:
        return {"label": f"pead {ticker}", "verdict": "no qualifying gaps"}
    rets = pd.Series(dict(rows))
    rets.index = pd.to_datetime(rets.index)
    return {"ticker": ticker, "events": len(rets),
            "drift": _summary(rets, f"{ticker} {gap_threshold:.0%}-gap drift {hold_days}d")}


if __name__ == "__main__":
    import json
    for t in ["SPY", "QQQ", "ASTS"]:
        print(json.dumps(study_overnight_split(t), indent=2, default=str))
        print(json.dumps(study_pead(t), indent=2, default=str))
