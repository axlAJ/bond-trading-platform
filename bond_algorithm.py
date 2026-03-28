"""
Bond Trading Algorithm — Philip AJ Sogah Bond Trading Platform
===============================================================
Generates buy/sell signals for bond ETFs using four independent signal layers:

  1. Yield Curve Signal     — curve shape, inversion, spread dynamics
  2. Rate Momentum Signal   — direction and velocity of rate changes
  3. Credit Spread Signal   — high yield vs investment grade divergence
  4. Price Momentum Signal  — ETF price trend and mean reversion

All four signals are fused into a composite BOND SCORE (-100 to +100):
  +100 = strong buy (rates falling, curve normalizing, credit tightening)
  -100 = strong sell (rates rising, curve inverting, credit widening)
     0 = neutral / hold

Bond-specific logic:
  - Bonds RISE when interest rates FALL (inverse relationship)
  - Long duration bonds (TLT) are MORE sensitive to rate changes
  - Inverted yield curve = recession risk = favor short duration (SHY)
  - High yield spreads widening = credit stress = reduce HYG exposure
  - Fed policy direction is the single most important macro driver
"""

from dataclasses import dataclass, field
from typing import Optional
from bond_data import BondQuote, YieldCurve, MacroSnapshot, BOND_ETFS


# ── SIGNAL STRUCTURES ─────────────────────────────────────────

@dataclass
class SignalComponent:
    name:   str
    score:  float    # -100 to +100
    reason: str
    weight: float    # contribution to composite


@dataclass
class BondSignal:
    symbol:          str
    action:          str     # BUY | SELL | HOLD
    strength:        str     # STRONG | MODERATE | WEAK
    composite_score: float   # -100 to +100
    confidence:      float   # 0-100%
    components:      list[SignalComponent]
    entry_price:     float
    target_price:    float
    stop_price:      float
    duration_fit:    str     # why this ETF fits current conditions
    risk_level:      str     # LOW | MEDIUM | HIGH
    rationale:       str     # plain English explanation


@dataclass
class PortfolioAllocation:
    """Recommended allocation across bond ETF universe."""
    allocations:  dict[str, float]   # symbol → % of portfolio
    total_risk:   str
    yield_target: float
    duration:     str
    rationale:    str


# ── YIELD CURVE SIGNAL ────────────────────────────────────────

class YieldCurveSignal:
    """
    Generates trading signals from yield curve shape and dynamics.

    Key relationships:
    - Normal curve (10Y > 2Y) → economy healthy → moderate bond exposure
    - Flat curve → uncertainty → reduce duration risk
    - Inverted curve (10Y < 2Y) → recession warning → buy TLT (long bonds)
      eventually rally as Fed cuts rates, short HYG (credit risk rises)
    - Spread narrowing → curve normalizing → sell TLT, buy equities
    """

    WEIGHT = 0.35   # highest weight — yield curve is the primary bond driver

    def score(self, yc: YieldCurve, symbol: str) -> SignalComponent:
        duration = BOND_ETFS.get(symbol, {}).get("duration", "intermediate")
        risk     = BOND_ETFS.get(symbol, {}).get("risk", "medium")
        spread   = yc.spread_10_2

        if yc.shape == "inverted":
            # Inverted curve: rates will eventually fall → long bonds win
            # But credit risk rises → avoid HYG
            if duration == "long":
                s = 65.0    # TLT — buy, rates will fall eventually
                reason = f"Inverted curve ({spread:.2f}%) signals eventual rate cuts — long bonds favored"
            elif risk == "credit":
                s = -70.0   # HYG/LQD — avoid, credit spreads widen in recessions
                reason = f"Inverted curve signals recession risk — credit bonds disfavored"
            else:
                s = 20.0    # intermediate — neutral slightly positive
                reason = f"Inverted curve ({spread:.2f}%) — intermediate duration modest opportunity"

        elif yc.shape == "flat":
            if duration == "short":
                s = 40.0    # SHY — best risk/reward in flat curve
                reason = f"Flat curve ({spread:.2f}%) — short duration optimal risk/reward"
            elif duration == "long":
                s = -20.0   # TLT — less attractive, little term premium
                reason = f"Flat curve — limited term premium for long duration"
            else:
                s = 10.0
                reason = f"Flat curve — neutral on intermediate duration"

        else:  # normal
            if duration == "long":
                s = -15.0   # normal curve → less urgency for long bonds
                reason = f"Normal curve ({spread:.2f}%) — long bonds less attractive"
            elif duration == "short":
                s = 25.0    # short duration safer in rising rate environment
                reason = f"Normal curve — short duration lower rate risk"
            else:
                s = 30.0    # intermediate bonds well-positioned
                reason = f"Normal curve ({spread:.2f}%) — intermediate bonds well-positioned"

        # Fed funds rate adjustment
        if yc.fed_funds > 5.0:
            s -= 15.0   # high rates = headwind for all bonds
            reason += f" | Fed at {yc.fed_funds:.2f}% — rate headwind"
        elif yc.fed_funds < 2.0:
            s += 15.0   # low rates = tailwind
            reason += f" | Low Fed rate {yc.fed_funds:.2f}% — tailwind"

        return SignalComponent(
            name   = "Yield Curve",
            score  = max(-100, min(100, s)),
            reason = reason,
            weight = self.WEIGHT,
        )


# ── RATE MOMENTUM SIGNAL ──────────────────────────────────────

class RateMomentumSignal:
    """
    Measures direction and velocity of interest rate changes.

    Bond price rule: rates UP → bond prices DOWN, rates DOWN → bond prices UP
    Momentum matters: accelerating rate moves amplify price moves.
    """

    WEIGHT = 0.25

    def score(self, yc: YieldCurve, prev_yc: Optional[YieldCurve], symbol: str) -> SignalComponent:
        duration = BOND_ETFS.get(symbol, {}).get("duration", "intermediate")

        if prev_yc is None:
            return SignalComponent("Rate Momentum", 0.0, "Insufficient history for momentum", self.WEIGHT)

        # Rate change (positive = rates rising = bond price falling)
        rate_change_10y = yc.y10 - prev_yc.y10
        rate_change_2y  = yc.y2  - prev_yc.y2

        # Duration multiplier — long bonds are more sensitive
        duration_mult = {"long": 2.5, "intermediate": 1.5, "short": 0.8}.get(duration, 1.5)

        # Score: negative rate change (falling rates) = positive bond signal
        raw_score = -rate_change_10y * duration_mult * 50

        # Spread change signal
        spread_change = (yc.spread_10_2 - prev_yc.spread_10_2)
        if spread_change > 0.1:
            raw_score += 10   # curve steepening = rates falling at long end
        elif spread_change < -0.1:
            raw_score -= 10   # curve flattening

        direction = "falling" if rate_change_10y < 0 else "rising"
        reason = (f"10Y rate {direction} {abs(rate_change_10y):.3f}% → "
                  f"{'tailwind' if rate_change_10y < 0 else 'headwind'} for {duration} duration")

        return SignalComponent(
            name   = "Rate Momentum",
            score  = max(-100, min(100, raw_score)),
            reason = reason,
            weight = self.WEIGHT,
        )


# ── CREDIT SPREAD SIGNAL ──────────────────────────────────────

class CreditSpreadSignal:
    """
    Analyzes high yield and credit spreads for risk-on/risk-off signals.

    High yield spread = extra yield investors demand for credit risk.
    Wide spreads = fear, credit stress → avoid HYG, favor Treasuries
    Tight spreads = confidence, risk appetite → HYG attractive
    """

    WEIGHT = 0.20

    # Historical reference points
    SPREAD_WIDE    = 6.0   # stress / recession territory
    SPREAD_NORMAL  = 4.0   # normal credit environment
    SPREAD_TIGHT   = 3.0   # risk-on / expensive

    def score(self, hy_spread: float, symbol: str) -> SignalComponent:
        risk = BOND_ETFS.get(symbol, {}).get("risk", "medium")

        if hy_spread <= 0:
            return SignalComponent("Credit Spread", 0.0, "No credit spread data", self.WEIGHT)

        if risk == "credit":   # HYG, LQD
            if hy_spread > self.SPREAD_WIDE:
                s = -80.0
                reason = f"HY spread {hy_spread:.2f}% — extreme credit stress, avoid"
            elif hy_spread > self.SPREAD_NORMAL:
                s = -30.0
                reason = f"HY spread {hy_spread:.2f}% — elevated credit risk"
            elif hy_spread < self.SPREAD_TIGHT:
                s = 60.0
                reason = f"HY spread {hy_spread:.2f}% — tight spreads, credit favorable"
            else:
                s = 20.0
                reason = f"HY spread {hy_spread:.2f}% — normal credit environment"

        elif risk in ("high_rate", "medium_rate"):  # Treasury ETFs
            # Inverse: wide credit spreads = flight to safety = Treasuries rally
            if hy_spread > self.SPREAD_WIDE:
                s = 70.0
                reason = f"HY spread {hy_spread:.2f}% — flight to safety boosts Treasuries"
            elif hy_spread > self.SPREAD_NORMAL:
                s = 30.0
                reason = f"HY spread {hy_spread:.2f}% — mild flight to quality"
            else:
                s = 0.0
                reason = f"HY spread {hy_spread:.2f}% — no flight to safety premium"
        else:
            s = 0.0
            reason = f"HY spread {hy_spread:.2f}% — neutral for this asset class"

        return SignalComponent(
            name   = "Credit Spread",
            score  = max(-100, min(100, s)),
            reason = reason,
            weight = self.WEIGHT,
        )


# ── PRICE MOMENTUM SIGNAL ─────────────────────────────────────

class PriceMomentumSignal:
    """
    Technical momentum signal on ETF price action.
    Uses simple moving average crossover and mean reversion.
    """

    WEIGHT = 0.20

    def score(self, quote: BondQuote, bars: list[dict]) -> SignalComponent:
        if len(bars) < 10:
            return SignalComponent("Price Momentum", 0.0, "Insufficient price history", self.WEIGHT)

        closes = [b["close"] for b in bars[-20:]]
        current = quote.price or closes[-1]

        sma5  = sum(closes[-5:])  / 5
        sma20 = sum(closes[-20:]) / min(len(closes), 20)

        # Mean reversion: how far from 20-day average
        deviation_pct = (current - sma20) / sma20 * 100

        # Momentum: 5-day SMA vs 20-day SMA
        if sma5 > sma20 * 1.005:
            momentum_score = 40.0    # bullish crossover
            momentum_str   = "bullish (5D > 20D SMA)"
        elif sma5 < sma20 * 0.995:
            momentum_score = -40.0   # bearish crossover
            momentum_str   = "bearish (5D < 20D SMA)"
        else:
            momentum_score = 0.0
            momentum_str   = "neutral"

        # Mean reversion adjustment
        if deviation_pct > 3:
            momentum_score -= 20    # overbought
        elif deviation_pct < -3:
            momentum_score += 20    # oversold

        reason = (f"Price momentum {momentum_str} | "
                  f"Current ${current:.2f} vs 20D avg ${sma20:.2f} "
                  f"({deviation_pct:+.1f}%)")

        return SignalComponent(
            name   = "Price Momentum",
            score  = max(-100, min(100, momentum_score)),
            reason = reason,
            weight = self.WEIGHT,
        )


# ── MAIN BOND ALGORITHM ───────────────────────────────────────

class BondAlgorithm:
    """
    Master bond trading algorithm.
    Fuses four signal layers into actionable buy/sell/hold signals
    with position sizing, targets, and stops.
    """

    def __init__(self):
        self.yield_curve_signal  = YieldCurveSignal()
        self.rate_momentum_signal = RateMomentumSignal()
        self.credit_spread_signal = CreditSpreadSignal()
        self.price_momentum_signal = PriceMomentumSignal()
        self._prev_yield_curve: Optional[YieldCurve] = None

    def analyse(self,
                symbol:  str,
                quote:   BondQuote,
                macro:   Optional[MacroSnapshot],
                bars:    list[dict] = None) -> BondSignal:
        """
        Run full signal analysis for a single bond ETF.
        """
        components = []
        yc = macro.yield_curve if macro else None
        hy = macro.hy_spread   if macro else 0

        # 1. Yield curve signal
        if yc:
            components.append(self.yield_curve_signal.score(yc, symbol))
        else:
            components.append(SignalComponent("Yield Curve", 0, "No yield curve data", YieldCurveSignal.WEIGHT))

        # 2. Rate momentum signal
        components.append(self.rate_momentum_signal.score(yc, self._prev_yield_curve, symbol))

        # 3. Credit spread signal
        components.append(self.credit_spread_signal.score(hy, symbol))

        # 4. Price momentum signal
        components.append(self.price_momentum_signal.score(quote, bars or []))

        # Fuse signals into composite score
        composite = sum(c.score * c.weight for c in components)
        composite = max(-100, min(100, composite))

        # Determine action and strength
        action, strength = self._classify(composite)

        # Position sizing and risk targets
        price  = quote.price
        target = self._target(price, composite, symbol)
        stop   = self._stop(price, composite, symbol)

        # Confidence = agreement between signals
        scores    = [c.score for c in components]
        same_sign = sum(1 for s in scores if (s > 0) == (composite > 0))
        confidence = (same_sign / len(scores)) * 100

        return BondSignal(
            symbol          = symbol,
            action          = action,
            strength        = strength,
            composite_score = round(composite, 2),
            confidence      = round(confidence, 1),
            components      = components,
            entry_price     = round(price, 4),
            target_price    = round(target, 4),
            stop_price      = round(stop, 4),
            duration_fit    = self._duration_fit(symbol, yc),
            risk_level      = BOND_ETFS.get(symbol, {}).get("risk", "medium"),
            rationale       = self._rationale(composite, yc, symbol),
        )

    def analyse_all(self,
                    quotes: dict,
                    macro:  Optional[MacroSnapshot],
                    bars:   dict = None) -> dict[str, BondSignal]:
        """Analyse all bond ETFs and return ranked signals."""
        signals = {}
        for symbol, quote in quotes.items():
            b = (bars or {}).get(symbol, [])
            signals[symbol] = self.analyse(symbol, quote, macro, b)
        if macro:
            self._prev_yield_curve = macro.yield_curve
        return signals

    def recommend_allocation(self,
                              signals: dict[str, BondSignal],
                              macro:   Optional[MacroSnapshot]) -> PortfolioAllocation:
        """
        Recommend portfolio allocation across bond ETFs
        based on current signals and macro environment.
        """
        yc    = macro.yield_curve if macro else None
        alloc = {}

        # Start with signal-weighted allocation
        positive = {s: sig for s, sig in signals.items() if sig.composite_score > 10}
        negative = {s: sig for s, sig in signals.items() if sig.composite_score < -10}
        neutral  = {s: sig for s, sig in signals.items() if -10 <= sig.composite_score <= 10}

        total_positive = sum(abs(s.composite_score) for s in positive.values())

        if total_positive > 0:
            for sym, sig in positive.items():
                alloc[sym] = round((abs(sig.composite_score) / total_positive) * 80, 1)
        for sym in neutral:
            alloc[sym] = 5.0
        for sym in negative:
            alloc[sym] = 0.0

        # Ensure allocations sum to 100
        total = sum(alloc.values())
        if total < 100 and alloc:
            top = max(alloc, key=alloc.get)
            alloc[top] += 100 - total

        shape     = yc.shape if yc else "unknown"
        duration  = "short" if shape == "inverted" else "intermediate" if shape == "flat" else "mixed"
        yt        = sum(yc.y2, yc.y10) / 2 if yc else 0

        return PortfolioAllocation(
            allocations  = alloc,
            total_risk   = "LOW" if shape == "inverted" else "MEDIUM",
            yield_target = round(yt, 2),
            duration     = duration,
            rationale    = f"Yield curve is {shape} — favoring {duration} duration bonds",
        )

    # ── helpers ───────────────────────────────────────────────

    def _classify(self, score: float) -> tuple[str, str]:
        if score >= 60:   return "BUY",  "STRONG"
        if score >= 25:   return "BUY",  "MODERATE"
        if score >= 10:   return "BUY",  "WEAK"
        if score <= -60:  return "SELL", "STRONG"
        if score <= -25:  return "SELL", "MODERATE"
        if score <= -10:  return "SELL", "WEAK"
        return "HOLD", "NEUTRAL"

    def _target(self, price: float, score: float, symbol: str) -> float:
        duration = BOND_ETFS.get(symbol, {}).get("duration", "intermediate")
        mult     = {"long": 0.04, "intermediate": 0.025, "short": 0.012}.get(duration, 0.025)
        direction = 1 if score > 0 else -1
        return price * (1 + direction * abs(score) / 100 * mult)

    def _stop(self, price: float, score: float, symbol: str) -> float:
        duration = BOND_ETFS.get(symbol, {}).get("duration", "intermediate")
        mult     = {"long": 0.02, "intermediate": 0.012, "short": 0.006}.get(duration, 0.012)
        direction = 1 if score > 0 else -1
        return price * (1 - direction * mult)

    def _duration_fit(self, symbol: str, yc: Optional[YieldCurve]) -> str:
        if not yc:
            return "No yield curve data available"
        d = BOND_ETFS.get(symbol, {}).get("duration", "intermediate")
        fits = {
            ("long",         "inverted"): "Best fit — inverted curve precedes rate cuts, long bonds rally",
            ("long",         "flat"):     "Moderate fit — some term premium, limited upside",
            ("long",         "normal"):   "Poor fit — normal curve limits long bond upside",
            ("short",        "inverted"): "Safe haven — high short yields, low duration risk",
            ("short",        "flat"):     "Good fit — competitive yield, minimal rate risk",
            ("short",        "normal"):   "Moderate fit — lower yield but stable",
            ("intermediate", "inverted"): "Moderate fit — balance of yield and safety",
            ("intermediate", "flat"):     "Good fit — balanced risk/reward",
            ("intermediate", "normal"):   "Good fit — captures yield curve steepness",
        }
        return fits.get((d, yc.shape), "Standard fit for current conditions")

    def _rationale(self, score: float, yc: Optional[YieldCurve], symbol: str) -> str:
        action = "buy" if score > 0 else "sell" if score < 0 else "hold"
        shape  = yc.shape if yc else "unknown"
        name   = BOND_ETFS.get(symbol, {}).get("name", symbol)
        return (f"{name}: {action.upper()} signal (score {score:+.0f}) in a "
                f"{shape} yield curve environment. "
                f"{'Rates expected to fall — bond prices rise.' if score > 30 else ''}"
                f"{'Rates expected to rise — bond prices fall.' if score < -30 else ''}"
                f"{'Mixed signals — monitor closely.' if abs(score) <= 30 else ''}")
