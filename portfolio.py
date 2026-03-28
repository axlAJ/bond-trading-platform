"""
Portfolio & Risk Management — Philip AJ Sogah Bond Trading Platform
====================================================================
Tracks positions, P&L, risk metrics, and enforces risk limits.

Risk Management Rules:
  - Max position size: 25% of portfolio per ETF
  - Max portfolio duration risk: configurable
  - Stop loss: enforced per position
  - Daily loss limit: halt trading if exceeded
  - Concentration limit: no single ETF > 30%
"""

import json
import os
import math
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional
from bond_data import BOND_ETFS


# ── DATA STRUCTURES ───────────────────────────────────────────

@dataclass
class Position:
    symbol:       str
    name:         str
    action:       str      # LONG | SHORT
    quantity:     float
    entry_price:  float
    current_price:float
    target_price: float
    stop_price:   float
    opened_at:    str
    signal_score: float
    status:       str = "OPEN"   # OPEN | CLOSED | STOPPED
    closed_at:    str = ""
    exit_price:   float = 0.0
    pnl:          float = 0.0
    pnl_pct:      float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.entry_price

    @property
    def unrealized_pnl(self) -> float:
        if self.action == "LONG":
            return (self.current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - self.current_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0
        return self.unrealized_pnl / self.cost_basis * 100


@dataclass
class RiskMetrics:
    total_value:       float
    cash:              float
    invested:          float
    unrealized_pnl:    float
    realized_pnl:      float
    total_pnl:         float
    total_pnl_pct:     float
    daily_pnl:         float
    max_drawdown:      float
    win_rate:          float
    total_trades:      int
    open_positions:    int
    largest_position:  float   # % of portfolio
    concentration_ok:  bool
    daily_limit_ok:    bool
    timestamp:         str


# ── PORTFOLIO TRACKER ─────────────────────────────────────────

class Portfolio:
    """
    Tracks all bond ETF positions, P&L, and enforces risk limits.
    Persists state to JSON so it survives restarts.
    """

    SAVE_FILE = "portfolio_state.json"

    def __init__(self,
                 starting_cash:      float = 100_000.0,
                 max_position_pct:   float = 25.0,
                 daily_loss_limit:   float = 2.0,
                 max_concentration:  float = 30.0):
        """
        Args:
            starting_cash:     paper trading capital in USD
            max_position_pct:  max single position as % of portfolio
            daily_loss_limit:  halt trading if daily loss exceeds this %
            max_concentration: max % in any single ETF
        """
        self.starting_cash     = starting_cash
        self.max_position_pct  = max_position_pct
        self.daily_loss_limit  = daily_loss_limit
        self.max_concentration = max_concentration

        self.cash:       float          = starting_cash
        self.positions:  dict[str, Position] = {}
        self.history:    list[Position] = []
        self._peak_value: float         = starting_cash
        self._daily_start_value: float  = starting_cash
        self._daily_date: str           = datetime.now().strftime("%Y-%m-%d")

        self._load()

    # ── TRADE EXECUTION ───────────────────────────────────────

    def open_position(self,
                      symbol:       str,
                      action:       str,
                      price:        float,
                      signal_score: float,
                      target:       float,
                      stop:         float,
                      size_pct:     float = None) -> Optional[Position]:
        """
        Open a new position. Returns Position if successful, None if risk check fails.
        """
        # Risk checks
        ok, reason = self._pre_trade_checks(symbol, price, action, size_pct)
        if not ok:
            print(f"  ⚠️  RISK BLOCK: {symbol} {action} — {reason}")
            return None

        # Position sizing
        portfolio_value = self._total_value(price)
        pct = size_pct if size_pct else self._size_from_signal(signal_score)
        pct = min(pct, self.max_position_pct)
        capital = portfolio_value * (pct / 100)
        quantity = capital / price

        cost = quantity * price
        if cost > self.cash:
            print(f"  ⚠️  Insufficient cash: need ${cost:.2f}, have ${self.cash:.2f}")
            return None

        self.cash -= cost
        pos = Position(
            symbol        = symbol,
            name          = BOND_ETFS.get(symbol, {}).get("name", symbol),
            action        = action.upper(),
            quantity      = round(quantity, 4),
            entry_price   = price,
            current_price = price,
            target_price  = target,
            stop_price    = stop,
            opened_at     = datetime.now(timezone.utc).isoformat(),
            signal_score  = signal_score,
        )
        self.positions[symbol] = pos
        self._save()

        print(f"  📊 POSITION OPENED  {action} {symbol} "
              f"@ ${price:.4f} | qty={quantity:.2f} | "
              f"T={target:.4f} S={stop:.4f} | "
              f"capital=${capital:.2f} ({pct:.1f}%)")
        return pos

    def update_prices(self, prices: dict[str, float]) -> list[str]:
        """
        Update position prices and check for stop/target hits.
        Returns list of exit events.
        """
        events = []
        self._check_daily_reset()

        for symbol, pos in list(self.positions.items()):
            price = prices.get(symbol)
            if not price:
                continue
            pos.current_price = price

            # Check stop loss
            stop_hit = (pos.action == "LONG"  and price <= pos.stop_price) or \
                       (pos.action == "SHORT" and price >= pos.stop_price)

            # Check target
            target_hit = (pos.action == "LONG"  and price >= pos.target_price) or \
                         (pos.action == "SHORT" and price <= pos.target_price)

            if stop_hit:
                result = self._close_position(symbol, price, "STOPPED")
                events.append(f"🛑 STOP HIT  {symbol} @ ${price:.4f} | PnL={result.pnl_pct:+.3f}%")
                print(f"  {events[-1]}")

            elif target_hit:
                result = self._close_position(symbol, price, "TARGET")
                events.append(f"✅ TARGET HIT  {symbol} @ ${price:.4f} | PnL={result.pnl_pct:+.3f}%")
                print(f"  {events[-1]}")

        self._save()
        return events

    def close_position(self, symbol: str, price: float, reason: str = "MANUAL") -> Optional[Position]:
        """Manually close a position."""
        if symbol not in self.positions:
            print(f"  No open position for {symbol}")
            return None
        return self._close_position(symbol, price, reason)

    # ── RISK METRICS ──────────────────────────────────────────

    def risk_metrics(self, current_prices: dict[str, float] = None) -> RiskMetrics:
        """Compute full portfolio risk metrics."""
        prices = current_prices or {}

        # Update current prices
        for sym, pos in self.positions.items():
            if sym in prices:
                pos.current_price = prices[sym]

        total_invested   = sum(p.cost_basis    for p in self.positions.values())
        unrealized_pnl   = sum(p.unrealized_pnl for p in self.positions.values())
        realized_pnl     = sum(p.pnl            for p in self.history)
        total_value      = self.cash + total_invested + unrealized_pnl
        total_pnl        = total_value - self.starting_cash
        total_pnl_pct    = total_pnl / self.starting_cash * 100

        # Daily P&L
        daily_pnl = total_value - self._daily_start_value
        daily_pnl_pct = daily_pnl / self._daily_start_value * 100

        # Max drawdown
        self._peak_value = max(self._peak_value, total_value)
        drawdown = (self._peak_value - total_value) / self._peak_value * 100

        # Win rate
        closed    = [p for p in self.history if p.status in ("TARGET", "MANUAL")]
        winners   = [p for p in closed if p.pnl > 0]
        win_rate  = len(winners) / len(closed) * 100 if closed else 0

        # Concentration check
        largest_pct = max(
            (p.market_value / total_value * 100 for p in self.positions.values()),
            default=0
        )

        return RiskMetrics(
            total_value      = round(total_value, 2),
            cash             = round(self.cash, 2),
            invested         = round(total_invested, 2),
            unrealized_pnl   = round(unrealized_pnl, 2),
            realized_pnl     = round(realized_pnl, 2),
            total_pnl        = round(total_pnl, 2),
            total_pnl_pct    = round(total_pnl_pct, 3),
            daily_pnl        = round(daily_pnl, 2),
            max_drawdown     = round(drawdown, 3),
            win_rate         = round(win_rate, 1),
            total_trades     = len(self.history),
            open_positions   = len(self.positions),
            largest_position = round(largest_pct, 1),
            concentration_ok = largest_pct <= self.max_concentration,
            daily_limit_ok   = abs(daily_pnl_pct) <= self.daily_loss_limit,
            timestamp        = datetime.now(timezone.utc).isoformat(),
        )

    def summary_table(self) -> str:
        """Print a formatted portfolio summary."""
        lines = [
            "═" * 70,
            f"  BOND PORTFOLIO — Philip AJ Sogah  |  philipajsogah.io",
            "═" * 70,
        ]
        if not self.positions:
            lines.append("  No open positions")
        else:
            lines.append(f"  {'SYMBOL':<8} {'ACTION':<6} {'QTY':>8} {'ENTRY':>8} {'CURRENT':>8} {'P&L%':>8} {'STATUS'}")
            lines.append("  " + "-" * 65)
            for sym, p in self.positions.items():
                lines.append(
                    f"  {sym:<8} {p.action:<6} {p.quantity:>8.2f} "
                    f"${p.entry_price:>7.3f} ${p.current_price:>7.3f} "
                    f"{p.unrealized_pnl_pct:>+7.3f}%"
                )
        lines.append("═" * 70)
        return "\n".join(lines)

    # ── INTERNAL ──────────────────────────────────────────────

    def _close_position(self, symbol: str, price: float, reason: str) -> Position:
        pos = self.positions.pop(symbol)
        pos.status     = reason
        pos.exit_price = price
        pos.closed_at  = datetime.now(timezone.utc).isoformat()
        pos.current_price = price

        if pos.action == "LONG":
            pos.pnl = (price - pos.entry_price) * pos.quantity
        else:
            pos.pnl = (pos.entry_price - price) * pos.quantity

        pos.pnl_pct = pos.pnl / pos.cost_basis * 100

        # Return cash
        self.cash += pos.quantity * price
        self.history.append(pos)
        return pos

    def _pre_trade_checks(self, symbol, price, action, size_pct) -> tuple[bool, str]:
        # Already have a position
        if symbol in self.positions:
            return False, f"Already have open position in {symbol}"

        # Daily loss limit
        metrics = self.risk_metrics()
        if not metrics.daily_limit_ok:
            return False, f"Daily loss limit hit — trading halted for today"

        # Concentration check
        tv = self._total_value(price)
        pct = (size_pct or self.max_position_pct)
        capital = tv * (pct / 100)
        if capital / tv * 100 > self.max_concentration:
            return False, f"Would exceed concentration limit of {self.max_concentration}%"

        # Cash check
        if capital > self.cash:
            return False, f"Insufficient cash"

        return True, "ok"

    def _size_from_signal(self, score: float) -> float:
        """Scale position size to signal strength."""
        abs_score = abs(score)
        if abs_score >= 70:   return 20.0
        if abs_score >= 50:   return 15.0
        if abs_score >= 30:   return 10.0
        return 5.0

    def _total_value(self, ref_price: float = None) -> float:
        invested = sum(p.market_value for p in self.positions.values())
        return self.cash + invested

    def _check_daily_reset(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._daily_date:
            self._daily_start_value = self._total_value()
            self._daily_date = today

    def _save(self):
        """Persist portfolio state to JSON."""
        state = {
            "cash":      self.cash,
            "positions": {s: vars(p) for s, p in self.positions.items()},
            "history":   [vars(p) for p in self.history[-100:]],  # keep last 100
            "peak":      self._peak_value,
            "daily_start": self._daily_start_value,
            "daily_date":  self._daily_date,
        }
        with open(self.SAVE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    def _load(self):
        """Load portfolio state from JSON if it exists."""
        if not os.path.exists(self.SAVE_FILE):
            return
        try:
            with open(self.SAVE_FILE) as f:
                state = json.load(f)
            self.cash            = state.get("cash", self.starting_cash)
            self._peak_value     = state.get("peak", self.starting_cash)
            self._daily_start_value = state.get("daily_start", self.starting_cash)
            self._daily_date     = state.get("daily_date", datetime.now().strftime("%Y-%m-%d"))

            for sym, pd in state.get("positions", {}).items():
                self.positions[sym] = Position(**pd)
            for pd in state.get("history", []):
                self.history.append(Position(**pd))
            print(f"  Portfolio loaded: ${self.cash:.2f} cash, {len(self.positions)} open positions")
        except Exception as e:
            print(f"  Could not load portfolio state: {e}")
