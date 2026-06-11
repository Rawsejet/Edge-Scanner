"""
scanner_premium.py — cash-secured put / wheel candidate scanner.

Edge being captured: the variance risk premium. Implied vol systematically
trades above subsequently-realized vol, so disciplined sellers of OTM puts on
quality underlyings get paid more than the actuarial fair price — IF position
sizing survives the occasional assignment.

Signal logic per ticker:
  1. IV/RV ratio: 30d ATM-ish IV vs 20d realized vol. Want ratio >= 1.2
     (you're being overpaid relative to recent movement).
  2. Strike selection: puts with approx delta in [-0.30, -0.15], DTE 21-45.
  3. Liquidity: OI >= 200, bid-ask spread <= 8% of mid (wide spreads eat
     the whole edge on entry+exit).
  4. Yield: annualized premium yield on collateral >= threshold.

Known failure modes (when this scanner lies to you):
  - Pre-earnings IV inflation: ratio looks juicy because a binary event is
    priced in. The earnings_within_dte flag is your guard — respect it.
  - Falling knives: high IV because the stock is collapsing. The 200-SMA
    trend filter rejects names in established downtrends.
  - Sizing: collateral per position should stay <= ~10% of account. The
    scanner finds candidates; it does not protect you from concentration.
"""

from __future__ import annotations

import pandas as pd

from common import (Signal, get_daily_bars, get_option_chain, put_delta_approx,
                    realized_vol, sma)

# --- parameters (tune these, then re-backtest before trusting changes) ------
MIN_IV_RV_RATIO = 1.20
DELTA_RANGE = (-0.30, -0.15)
DTE_RANGE = (21, 45)
MIN_OI = 200
MAX_SPREAD_PCT = 0.08
MIN_ANN_YIELD = 0.15          # 15% annualized on collateral
REQUIRE_ABOVE_200SMA = True


def earnings_within(ticker: str, dte: int) -> bool:
    """Best-effort earnings check via yfinance calendar."""
    try:
        import yfinance as yf
        cal = yf.Ticker(ticker).calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if dates:
            from datetime import datetime, timezone
            d0 = dates[0]
            days = (pd.Timestamp(d0).date() - datetime.now(timezone.utc).date()).days
            return 0 <= days <= dte
    except Exception:
        pass
    return False


def scan_ticker(ticker: str) -> list[Signal]:
    bars = get_daily_bars(ticker)
    if bars.empty or len(bars) < 210:
        return []
    spot = float(bars["close"].iloc[-1])

    if REQUIRE_ABOVE_200SMA and spot < float(sma(bars["close"], 200).iloc[-1]):
        return []  # don't sell puts into a downtrend

    rv20 = realized_vol(bars["close"], 20)
    chain = get_option_chain(ticker, max_dte=DTE_RANGE[1])
    if chain.empty:
        return []

    puts = chain[(chain["type"] == "put") & chain["dte"].between(*DTE_RANGE)].copy()
    if puts.empty:
        return []

    # IV/RV using near-the-money put IV as proxy for ATM IV
    ntm = puts[(puts["strike"] / spot).between(0.95, 1.05)]
    iv30 = float(ntm["iv"].median()) if not ntm.empty else float(puts["iv"].median())
    if not rv20 or pd.isna(rv20) or iv30 <= 0:
        return []
    ratio = iv30 / rv20
    if ratio < MIN_IV_RV_RATIO:
        return []

    # Prefer real greeks (Tradier/ORATS); approximate only when absent
    if "delta" not in puts.columns or puts["delta"].abs().max() == 0:
        puts["delta"] = puts.apply(
            lambda r: put_delta_approx(spot, r["strike"], r["iv"], r["dte"]), axis=1)
    cand = puts[
        puts["delta"].between(*DELTA_RANGE)
        & (puts["oi"] >= MIN_OI)
        & (puts["spread_pct"] <= MAX_SPREAD_PCT)
    ].copy()
    if cand.empty:
        return []

    # annualized yield on cash collateral (strike * 100 per contract)
    cand["ann_yield"] = (cand["mid"] / cand["strike"]) * (365 / cand["dte"])
    cand = cand[cand["ann_yield"] >= MIN_ANN_YIELD]
    if cand.empty:
        return []

    erns = earnings_within(ticker, int(cand["dte"].max()))
    best = cand.sort_values("ann_yield", ascending=False).iloc[0]
    return [Signal(
        scanner="PREMIUM",
        ticker=ticker,
        headline=f"CSP {best['strike']:g}P {best['expiry']} @ {best['mid']:.2f}",
        details={
            "iv_rv": f"{ratio:.2f}",
            "delta": f"{best['delta']:.2f}",
            "dte": int(best["dte"]),
            "ann_yield": f"{best['ann_yield']:.0%}",
            "oi": int(best["oi"]),
            "earnings_in_window": erns,   # if True, you are selling an event
        },
    )]


def scan(universe: list[str]) -> list[Signal]:
    out: list[Signal] = []
    for t in universe:
        out.extend(scan_ticker(t))
    return out
