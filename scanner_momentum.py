"""
scanner_momentum.py — momentum / trend-following scanner.

Edge being captured: cross-sectional and time-series momentum — the most
robust anomaly in the academic literature (Jegadeesh & Titman 1993 onward).
Winners over 3-12 months tend to keep winning over the next 1-3 months.
The edge is real but slow: it pays over weeks/months of holding, not intraday.

Signal logic per ticker:
  1. Trend alignment: close > 50SMA > 200SMA (stage-2 uptrend structure).
  2. 12-1 momentum: total return over the last 252 trading days EXCLUDING the
     most recent 21 (skip-month avoids short-term reversal contamination).
  3. Trend strength: ADX(14) >= 20 — moving, not chopping.
  4. Proximity to highs: within 10% of 52-week high (strength begets strength;
     buying "cheap" laggards is the anti-momentum trade).
  5. Liquidity: 20d average dollar volume floor so fills don't eat the edge.

Known failure modes:
  - Momentum crashes: after sharp bear-market bottoms, the strategy gets run
    over as beaten-down junk rips. The 200SMA market regime filter on SPY
    (check_regime) is the cheap insurance — don't take signals when it's off.
  - Whipsaw in range-bound tape: ADX filter helps but doesn't eliminate it.
  - This generates ENTRIES. Exits (trail stop, e.g. 3x ATR or close < 50SMA)
    matter more than entries and must be defined before any position is opened.
"""

from __future__ import annotations

from common import Signal, adx, atr, get_daily_bars, sma

# --- parameters --------------------------------------------------------------
MIN_MOM_12_1 = 0.20          # >= +20% over months 2-12
MIN_ADX = 20
MAX_PCT_OFF_HIGH = 0.10
MIN_AVG_DOLLAR_VOL = 20e6    # $20M/day
REGIME_TICKER = "SPY"


def check_regime() -> bool:
    """Risk-on only when SPY is above its 200SMA. Momentum's worst drawdowns
    cluster when this is False."""
    bars = get_daily_bars(REGIME_TICKER)
    if bars.empty or len(bars) < 210:
        return False
    return float(bars["close"].iloc[-1]) > float(sma(bars["close"], 200).iloc[-1])


def scan_ticker(ticker: str) -> list[Signal]:
    bars = get_daily_bars(ticker)
    if bars.empty or len(bars) < 260:
        return []
    close = bars["close"]
    spot = float(close.iloc[-1])

    s50, s200 = float(sma(close, 50).iloc[-1]), float(sma(close, 200).iloc[-1])
    if not (spot > s50 > s200):
        return []

    # 12-1 momentum
    if len(close) < 252:
        return []
    mom = float(close.iloc[-21] / close.iloc[-252] - 1)
    if mom < MIN_MOM_12_1:
        return []

    a = float(adx(bars).iloc[-1])
    if a < MIN_ADX:
        return []

    hi52 = float(close.tail(252).max())
    off_high = 1 - spot / hi52
    if off_high > MAX_PCT_OFF_HIGH:
        return []

    advol = float((close * bars["volume"]).tail(20).mean())
    if advol < MIN_AVG_DOLLAR_VOL:
        return []

    trail = 3 * float(atr(bars).iloc[-1])
    return [Signal(
        scanner="MOMENTUM",
        ticker=ticker,
        headline=f"stage-2 uptrend, 12-1 mom {mom:+.0%}",
        details={
            "adx": f"{a:.0f}",
            "off_52w_high": f"{off_high:.1%}",
            "suggested_trail_stop": f"{spot - trail:.2f} (3xATR)",
            "avg_$vol": f"${advol/1e6:.0f}M",
        },
    )]


def scan(universe: list[str]) -> list[Signal]:
    if not check_regime():
        print("[MOMENTUM] regime filter OFF (SPY < 200SMA) — no signals taken")
        return []
    out: list[Signal] = []
    for t in universe:
        out.extend(scan_ticker(t))
    return out
