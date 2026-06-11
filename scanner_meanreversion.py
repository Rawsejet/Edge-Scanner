"""
scanner_meanreversion.py — short-term mean reversion scanner.

Edge being captured: short-horizon reversal in liquid large-caps. Sharp 2-5
day selloffs in stocks that are in healthy long-term uptrends tend to snap
back. This is the classic RSI(2) / Connors-style setup. The edge is small per
trade, decays fast, and ONLY works with the trend filter — buying oversold
stocks in downtrends is how people catch knives.

Signal logic per ticker:
  1. Long-term trend filter: close > 200SMA. Non-negotiable. Reversion is
     traded WITH the primary trend, against the short-term move.
  2. Oversold trigger: RSI(2) <= 10 (deeply washed out on a days scale).
  3. Stretch confirmation: z-score of close vs 20d mean <= -1.5.
  4. Liquidity floor — this is a large-cap strategy; in small caps the
     "oversold" stock is usually oversold for a reason you'll read about later.

Exit discipline (defines the trade, not the scanner):
  - Time stop: out in 5 trading days max, win or lose.
  - Or exit on RSI(2) > 60 / close back above 5SMA.
  - Hard stop wider than usual (reversion entries get worse before better);
    size smaller instead of stopping tighter.

Known failure modes:
  - Regime breaks: in genuine crashes everything is "oversold" all the way
    down. The SPY circuit breaker below stands down when the index itself is
    in freefall.
  - News-driven gaps: a stock down 20% on fraud allegations is not "mean
    reverting." Check WHY it's down before acting on any signal.
"""

from __future__ import annotations

from common import Signal, get_daily_bars, rsi, sma, zscore

# --- parameters --------------------------------------------------------------
MAX_RSI2 = 10
MAX_ZSCORE = -1.5
MIN_AVG_DOLLAR_VOL = 50e6      # large caps only
SPY_CRASH_GUARD_RSI = 25       # stand down if SPY itself is collapsing


def crash_guard() -> bool:
    bars = get_daily_bars("SPY")
    if bars.empty:
        return False
    return float(rsi(bars["close"], 14).iloc[-1]) > SPY_CRASH_GUARD_RSI


def scan_ticker(ticker: str) -> list[Signal]:
    bars = get_daily_bars(ticker)
    if bars.empty or len(bars) < 210:
        return []
    close = bars["close"]
    spot = float(close.iloc[-1])

    if spot < float(sma(close, 200).iloc[-1]):
        return []  # trend filter: longs only in uptrends

    r2 = float(rsi(close, 2).iloc[-1])
    if r2 > MAX_RSI2:
        return []

    z = float(zscore(close, 20).iloc[-1])
    if z > MAX_ZSCORE:
        return []

    advol = float((close * bars["volume"]).tail(20).mean())
    if advol < MIN_AVG_DOLLAR_VOL:
        return []

    drop5 = spot / float(close.iloc[-6]) - 1
    return [Signal(
        scanner="MEANREV",
        ticker=ticker,
        headline=f"oversold in uptrend, RSI(2)={r2:.0f}",
        details={
            "zscore20": f"{z:.2f}",
            "5d_move": f"{drop5:+.1%}",
            "plan": "time-stop 5d / exit RSI2>60",
            "check_news_first": True,
        },
    )]


def scan(universe: list[str]) -> list[Signal]:
    if not crash_guard():
        print("[MEANREV] SPY crash guard active — standing down")
        return []
    out: list[Signal] = []
    for t in universe:
        out.extend(scan_ticker(t))
    return out
