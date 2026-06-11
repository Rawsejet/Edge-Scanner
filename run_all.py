"""
run_all.py — daily driver for the scanner suite.

Run after the close (or pre-market) on darth-rawsejet:
    python run_all.py

Cron example (6:30pm CT weekdays):
    30 18 * * 1-5 cd /path/to/edge_scanners && /usr/bin/python3 run_all.py

Hard rules baked into this suite's philosophy:
  - Scanners produce CANDIDATES, not orders. A human reviews every signal.
  - No broker write access from any automated component, ever.
  - Any parameter change gets re-backtested before it touches live decisions.
"""

from __future__ import annotations

import os

import scanner_meanreversion
import scanner_momentum
import scanner_premium
from common import emit

# Universe: liquid optionable names + current wheel underlyings. Keep it small
# and high-quality; a 500-name universe mostly adds noise and rate limits.
UNIVERSE = [
    # current wheel names
    "ASTS", "IBIT", "GLD", "DIS", "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "GOOGL", "AMZN",
    # liquid premium-selling staples
    "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "GOOGL", "AMZN",
    "META", "TSLA", "PLTR", "COIN", "SOFI", "F", "INTC", "TQQQ", "DIS", "SOXL",
]

DISCORD_WEBHOOK = os.environ.get("SCANNER_DISCORD_WEBHOOK")  # optional


def main() -> None:
    signals = []
    signals += scanner_premium.scan(UNIVERSE)
    signals += scanner_momentum.scan(UNIVERSE)
    signals += scanner_meanreversion.scan(UNIVERSE)

    if not signals:
        print("No signals today. That is a valid and common output — "
              "forcing trades on no-signal days is where edges go to die.")
    emit(signals, DISCORD_WEBHOOK)


if __name__ == "__main__":
    main()
