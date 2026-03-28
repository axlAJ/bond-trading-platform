"""
Bond Data Layer — Philip AJ Sogah Bond Trading Platform
========================================================
Fetches live bond market data from two sources:
  1. Alpaca Markets  — real-time bond ETF prices (TLT, IEF, SHY, AGG, BND, HYG)
  2. FRED API        — Federal Reserve yield curve, interest rates, economic data

Bond ETF Reference:
  TLT  — iShares 20+ Year Treasury Bond ETF  (long duration, most rate-sensitive)
  IEF  — iShares 7-10 Year Treasury Bond ETF (intermediate duration)
  SHY  — iShares 1-3 Year Treasury Bond ETF  (short duration, low risk)
  AGG  — iShares Core US Aggregate Bond ETF  (broad market)
  BND  — Vanguard Total Bond Market ETF      (broad market alternative)
  HYG  — iShares iBoxx High Yield Corp Bond  (high yield / junk bonds)
  LQD  — iShares Investment Grade Corp Bond  (investment grade corporate)

FRED API Key: Free at https://fred.stlouisfed.org/docs/api/api_key.html
"""

import os
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional


# ── BOND ETF UNIVERSE ────────────────────────────────────────
BOND_ETFS = {
    "TLT": {"name": "20+ Year Treasury",    "duration": "long",         "risk": "high_rate"},
    "IEF": {"name": "7-10 Year Treasury",   "duration": "intermediate", "risk": "medium_rate"},
    "SHY": {"name": "1-3 Year Treasury",    "duration": "short",        "risk": "low_rate"},
    "AGG": {"name": "US Aggregate Bond",    "duration": "intermediate", "risk": "medium"},
    "BND": {"name": "Total Bond Market",    "duration": "intermediate", "risk": "medium"},
    "HYG": {"name": "High Yield Corporate", "duration": "intermediate", "risk": "credit"},
    "LQD": {"name": "Investment Grade Corp","duration": "intermediate", "risk": "credit"},
}

# FRED Series IDs for yield curve + macro data
FRED_SERIES = {
    "DGS2":   "2-Year Treasury Yield",
    "DGS5":   "5-Year Treasury Yield",
    "DGS10":  "10-Year Treasury Yield",
    "DGS30":  "30-Year Treasury Yield",
    "DFF":    "Federal Funds Rate",
    "T10Y2Y": "10Y-2Y Yield Spread (recession indicator)",
    "BAMLH0A0HYM2": "High Yield Spread",
    "CPIAUCSL": "CPI Inflation Rate",
}


# ── DATA STRUCTURES ───────────────────────────────────────────

@dataclass
class BondQuote:
    symbol:     str
    name:       str
    price:      float
    bid:        float
    ask:        float
    spread:     float
    volume:     int
    timestamp:  str
    change:     float = 0.0
    change_pct: float = 0.0


@dataclass
class YieldCurve:
    y2:       float   # 2-year yield
    y5:       float   # 5-year yield
    y10:      float   # 10-year yield
    y30:      float   # 30-year yield
    spread_10_2: float  # 10Y - 2Y spread (negative = inverted = recession signal)
    fed_funds: float
    shape:    str     # 'normal', 'flat', 'inverted'
    timestamp: str


@dataclass
class MacroSnapshot:
    yield_curve:  YieldCurve
    hy_spread:    float   # High yield spread — credit risk indicator
    inflation:    float   # CPI
    timestamp:    str


# ── ALPACA BOND DATA ──────────────────────────────────────────

class AlpacaBondData:
    """
    Fetches real-time bond ETF quotes from Alpaca REST API.
    Uses paper trading credentials — same keys you already have.
    """

    BASE_URL = "https://data.alpaca.markets/v2"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key    = api_key
        self.api_secret = api_secret

    def _get(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.BASE_URL}{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "APCA-API-KEY-ID":     self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception as e:
            print(f"Alpaca API error: {e}")
            return {}

    def get_quote(self, symbol: str) -> Optional[BondQuote]:
        """Get latest quote for a bond ETF."""
        data = self._get(f"/stocks/{symbol}/quotes/latest")
        q = data.get("quote", {})
        if not q:
            return None
        bid = float(q.get("bp", 0))
        ask = float(q.get("ap", 0))
        price = (bid + ask) / 2 if bid and ask else 0
        return BondQuote(
            symbol    = symbol,
            name      = BOND_ETFS.get(symbol, {}).get("name", symbol),
            price     = round(price, 4),
            bid       = round(bid, 4),
            ask       = round(ask, 4),
            spread    = round(ask - bid, 4),
            volume    = int(q.get("as", 0)) + int(q.get("bs", 0)),
            timestamp = q.get("t", datetime.now(timezone.utc).isoformat()),
        )

    def get_all_quotes(self) -> dict[str, BondQuote]:
        """Get quotes for all bond ETFs in the universe."""
        quotes = {}
        for symbol in BOND_ETFS:
            quote = self.get_quote(symbol)
            if quote:
                quotes[symbol] = quote
            time.sleep(0.1)  # rate limit protection
        return quotes

    def get_bars(self, symbol: str, days: int = 30) -> list[dict]:
        """Get historical OHLCV bars for a bond ETF."""
        end   = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        data  = self._get(f"/stocks/{symbol}/bars", {
            "timeframe": "1Day",
            "start":     start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end":       end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit":     days,
        })
        bars = data.get("bars", [])
        return [{"date": b["t"][:10], "open": b["o"], "high": b["h"],
                 "low": b["l"], "close": b["c"], "volume": b["v"]} for b in bars]


# ── FRED YIELD CURVE DATA ─────────────────────────────────────

class FREDData:
    """
    Fetches yield curve and macro data from the Federal Reserve (FRED).
    Free API key: https://fred.stlouisfed.org/docs/api/api_key.html
    Takes 30 seconds to sign up.
    """

    BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_latest(self, series_id: str) -> Optional[float]:
        """Get the latest value for a FRED data series."""
        params = {
            "series_id":      series_id,
            "api_key":        self.api_key,
            "file_type":      "json",
            "sort_order":     "desc",
            "limit":          5,
            "observation_end": datetime.now().strftime("%Y-%m-%d"),
        }
        url = self.BASE_URL + "?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            obs = data.get("observations", [])
            for o in obs:
                if o.get("value") not in (".", ""):
                    return float(o["value"])
        except Exception as e:
            print(f"FRED error ({series_id}): {e}")
        return None

    def get_yield_curve(self) -> Optional[YieldCurve]:
        """Build a full yield curve snapshot from FRED data."""
        y2  = self.get_latest("DGS2")
        y5  = self.get_latest("DGS5")
        y10 = self.get_latest("DGS10")
        y30 = self.get_latest("DGS30")
        fed = self.get_latest("DFF")
        spread = self.get_latest("T10Y2Y")

        if not all([y2, y10]):
            return None

        # Determine curve shape
        if spread is not None:
            if spread < -0.1:
                shape = "inverted"   # recession warning
            elif spread < 0.5:
                shape = "flat"       # caution
            else:
                shape = "normal"     # healthy
        else:
            shape = "unknown"

        return YieldCurve(
            y2          = y2 or 0,
            y5          = y5 or 0,
            y10         = y10 or 0,
            y30         = y30 or 0,
            spread_10_2 = spread or (y10 - y2 if y10 and y2 else 0),
            fed_funds   = fed or 0,
            shape       = shape,
            timestamp   = datetime.now(timezone.utc).isoformat(),
        )

    def get_macro_snapshot(self) -> Optional[MacroSnapshot]:
        """Full macro picture for bond trading decisions."""
        yc        = self.get_yield_curve()
        hy_spread = self.get_latest("BAMLH0A0HYM2")
        inflation = self.get_latest("CPIAUCSL")
        if not yc:
            return None
        return MacroSnapshot(
            yield_curve = yc,
            hy_spread   = hy_spread or 0,
            inflation   = inflation or 0,
            timestamp   = datetime.now(timezone.utc).isoformat(),
        )


# ── COMBINED DATA FEED ────────────────────────────────────────

class BondDataFeed:
    """
    Single interface combining Alpaca + FRED data.
    This is what the algorithm layer consumes.
    """

    def __init__(self,
                 alpaca_key:    str,
                 alpaca_secret: str,
                 fred_key:      str = None):
        self.alpaca = AlpacaBondData(alpaca_key, alpaca_secret)
        self.fred   = FREDData(fred_key) if fred_key else None
        self._quote_cache: dict = {}
        self._macro_cache: Optional[MacroSnapshot] = None
        self._last_macro_fetch: float = 0

    def quotes(self) -> dict[str, BondQuote]:
        """Get fresh quotes for all bond ETFs."""
        self._quote_cache = self.alpaca.get_all_quotes()
        return self._quote_cache

    def macro(self) -> Optional[MacroSnapshot]:
        """
        Get macro snapshot. Cached for 1 hour since FRED
        data updates once per day.
        """
        if not self.fred:
            return None
        now = time.time()
        if now - self._last_macro_fetch > 3600:
            self._macro_cache     = self.fred.get_macro_snapshot()
            self._last_macro_fetch = now
        return self._macro_cache

    def summary(self) -> dict:
        """Print a human-readable market summary."""
        quotes = self.quotes()
        macro  = self.macro()
        out = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bond_etfs": {s: {"price": q.price, "spread": q.spread} for s, q in quotes.items()},
        }
        if macro:
            out["yield_curve"] = {
                "2Y": macro.yield_curve.y2,
                "10Y": macro.yield_curve.y10,
                "spread": macro.yield_curve.spread_10_2,
                "shape": macro.yield_curve.shape,
                "fed_funds": macro.yield_curve.fed_funds,
            }
            out["hy_spread"]  = macro.hy_spread
        return out


# ── ENTRY POINT ───────────────────────────────────────────────

if __name__ == "__main__":
    key    = os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_SECRET")
    fred   = os.getenv("FRED_API_KEY")  # optional but recommended

    if not key or not secret:
        raise SystemExit("Set ALPACA_API_KEY and ALPACA_SECRET environment variables")

    feed = BondDataFeed(key, secret, fred)
    print("Fetching bond ETF quotes...")
    data = feed.summary()
    print(json.dumps(data, indent=2))
