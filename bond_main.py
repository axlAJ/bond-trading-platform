"""
Bond Trading Platform — Main Runner
Philip AJ Sogah | philipajsogah.io
====================================
Orchestrates the full bond trading pipeline:
  Data → Algorithm → Risk Check → Portfolio → Audit

Usage:
    export ALPACA_API_KEY="PKxxxxxxx"
    export ALPACA_SECRET="your_secret"
    export FRED_API_KEY="your_fred_key"   # free at fred.stlouisfed.org
    python3 bond_main.py
"""

import os
import time
import json
from datetime import datetime, timezone

from bond_data     import BondDataFeed
from bond_algorithm import BondAlgorithm
from portfolio     import Portfolio
from security      import SecurityManager


def run():
    print("""
╔══════════════════════════════════════════════════════════╗
║   BOND TRADING PLATFORM — Philip AJ Sogah                ║
║   philipajsogah.io  |  github.com/axlAJ                  ║
╚══════════════════════════════════════════════════════════╝
    """)

    # ── Load credentials ──────────────────────────────────────
    alpaca_key    = os.getenv("ALPACA_API_KEY")
    alpaca_secret = os.getenv("ALPACA_SECRET")
    fred_key      = os.getenv("FRED_API_KEY")

    if not alpaca_key or not alpaca_secret:
        raise SystemExit("Set ALPACA_API_KEY and ALPACA_SECRET environment variables")

    if not fred_key:
        print("  ⚠️  No FRED_API_KEY set — yield curve signals disabled")
        print("     Get a free key at: https://fred.stlouisfed.org/docs/api/api_key.html\n")

    # ── Initialize components ─────────────────────────────────
    print("  Initializing platform components...")
    security  = SecurityManager()
    data_feed = BondDataFeed(alpaca_key, alpaca_secret, fred_key)
    algorithm = BondAlgorithm()
    portfolio = Portfolio(starting_cash=100_000.0)

    print("  ✓ Security layer active")
    print("  ✓ Data feed connected")
    print("  ✓ Algorithm ready")
    print("  ✓ Portfolio loaded")
    print(f"\n  Paper capital: ${portfolio.cash:,.2f}")
    print(f"  Open positions: {len(portfolio.positions)}")
    print("\n" + "─" * 60)

    scan_interval = 60   # seconds between scans
    bars_cache    = {}   # cache historical bars

    while True:
        try:
            now = datetime.now(timezone.utc).strftime("%H:%M:%S")
            print(f"\n[{now}] Scanning bond markets...")

            # ── Check circuit breaker ─────────────────────────
            can_trade, reason = security.can_trade()
            if not can_trade:
                print(f"  ⚠️  Trading paused: {reason}")

            # ── Fetch live data ───────────────────────────────
            if not security.rate_limiter.check("alpaca_quote"):
                print("  Rate limit — skipping quote fetch")
                time.sleep(scan_interval)
                continue

            print("  Fetching bond ETF quotes...")
            quotes = data_feed.quotes()
            if not quotes:
                print("  No quotes received — market may be closed")
                security.circuit_breaker.record_api_error()
                time.sleep(scan_interval)
                continue

            security.circuit_breaker.record_api_success()

            # ── Fetch macro data (cached 1hr) ─────────────────
            macro = data_feed.macro()
            if macro and macro.yield_curve:
                yc = macro.yield_curve
                print(f"  Yield curve: 2Y={yc.y2:.2f}% 10Y={yc.y10:.2f}% "
                      f"spread={yc.spread_10_2:+.2f}% shape={yc.shape.upper()}")

            # ── Update portfolio prices ───────────────────────
            prices = {s: q.price for s, q in quotes.items() if q.price > 0}
            events = portfolio.update_prices(prices)
            for event in events:
                if "STOPPED" in event:
                    security.circuit_breaker.record_loss()
                elif "TARGET" in event:
                    security.circuit_breaker.record_win()

            # ── Run algorithm ─────────────────────────────────
            if not security.rate_limiter.check("algo_run"):
                print("  Algorithm rate limit — skipping this cycle")
                time.sleep(scan_interval)
                continue

            signals = algorithm.analyse_all(quotes, macro, bars_cache)

            # ── Print signals ─────────────────────────────────
            print(f"\n  {'SYMBOL':<6} {'ACTION':<6} {'SCORE':>7} {'CONF':>6} {'PRICE':>8}  RATIONALE")
            print("  " + "─" * 70)
            for sym, sig in sorted(signals.items(),
                                    key=lambda x: abs(x[1].composite_score),
                                    reverse=True):
                action_color = "BUY " if sig.action == "BUY" else "SELL" if sig.action == "SELL" else "HOLD"
                print(f"  {sym:<6} {action_color:<6} {sig.composite_score:>+7.1f} "
                      f"{sig.confidence:>5.1f}% "
                      f"${sig.entry_price:>7.3f}  "
                      f"{sig.rationale[:45]}")
                security.audit.signal_generated(sym, sig.action, sig.composite_score, sig.confidence)

            # ── Execute signals (paper trade) ─────────────────
            if can_trade:
                for sym, sig in signals.items():
                    # Skip if already in position
                    if sym in portfolio.positions:
                        continue

                    # Only act on strong signals
                    if sig.action == "BUY" and sig.composite_score >= 40:
                        ok, reason = security.validate_and_log_trade(
                            sym, "LONG", sig.entry_price,
                            1.0, sig.composite_score
                        )
                        if ok:
                            portfolio.open_position(
                                symbol       = sym,
                                action       = "LONG",
                                price        = sig.entry_price,
                                signal_score = sig.composite_score,
                                target       = sig.target_price,
                                stop         = sig.stop_price,
                            )

                    elif sig.action == "SELL" and sig.composite_score <= -40:
                        ok, reason = security.validate_and_log_trade(
                            sym, "SHORT", sig.entry_price,
                            1.0, sig.composite_score
                        )
                        if ok:
                            portfolio.open_position(
                                symbol       = sym,
                                action       = "SHORT",
                                price        = sig.entry_price,
                                signal_score = sig.composite_score,
                                target       = sig.target_price,
                                stop         = sig.stop_price,
                            )

            # ── Portfolio summary ─────────────────────────────
            metrics = portfolio.risk_metrics(prices)
            print(f"\n  Portfolio: ${metrics.total_value:,.2f} | "
                  f"P&L: {metrics.total_pnl_pct:+.3f}% | "
                  f"Positions: {metrics.open_positions} | "
                  f"Win rate: {metrics.win_rate:.1f}%")

            if not metrics.daily_limit_ok:
                print(f"  ⚠️  Daily loss limit approaching — reducing activity")
            if not metrics.concentration_ok:
                print(f"  ⚠️  Concentration limit exceeded — rebalancing needed")

            print(f"\n  Next scan in {scan_interval}s... (Ctrl+C to stop)")
            time.sleep(scan_interval)

        except KeyboardInterrupt:
            print("\n\n  Shutting down bond platform...")
            print(portfolio.summary_table())
            metrics = portfolio.risk_metrics()
            print(f"\n  Final P&L:    {metrics.total_pnl_pct:+.3f}%")
            print(f"  Total trades: {metrics.total_trades}")
            print(f"  Win rate:     {metrics.win_rate:.1f}%")
            print(f"  Max drawdown: {metrics.max_drawdown:.3f}%")
            print("\n  Platform stopped. All state saved.")
            break

        except Exception as e:
            security.circuit_breaker.record_api_error()
            print(f"  Error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run()
