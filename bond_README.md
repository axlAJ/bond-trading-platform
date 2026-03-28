# Bond Trading Platform
### AI-Powered Bond Market Analysis & Trading System

> *Live yield curve analysis from the Federal Reserve. Four-signal fusion algorithm. Enterprise-grade security. Real-time bond ETF signals.*

**Philip AJ Sogah** | [philipajsogah.io](https://philipajsogah.io) | philipaxl7@gmail.com

---

## Overview

The Bond Trading Platform is an independent research project combining live Federal Reserve yield curve data with a multi-signal bond trading algorithm. The system connects to two real-time data sources — Alpaca Markets for bond ETF prices and the FRED API for macroeconomic data — and generates actionable buy/sell/hold signals across a universe of 7 bond ETFs.

Built with enterprise-grade security including API key encryption, rate limiting, circuit breakers, and a tamper-evident audit trail.

---

## Live Output

```
╔══════════════════════════════════════════════════════════╗
║   BOND TRADING PLATFORM — Philip AJ Sogah                ║
║   philipajsogah.io  |  github.com/axlAJ                  ║
╚══════════════════════════════════════════════════════════╝

  ✓ Security layer active
  ✓ Data feed connected
  ✓ Algorithm ready
  ✓ Portfolio loaded

  Paper capital: $100,000.00
  Open positions: 0

[01:50:23] Scanning bond markets...
  Yield curve: 2Y=3.96% 10Y=4.42% spread=+0.56% shape=NORMAL

  SYMBOL  ACTION   SCORE   CONF    PRICE  RATIONALE
  ──────────────────────────────────────────────────────────
  HYG     BUY     +14.5  50.0%  $78.675  High Yield Corporate: BUY signal
  LQD     BUY     +14.5  50.0% $107.425  Investment Grade Corp: BUY signal
  IEF     BUY     +10.5  25.0%  $94.650  7-10 Year Treasury: BUY signal
  AGG     BUY     +10.5  25.0%  $98.535  US Aggregate Bond: BUY signal
  BND     BUY     +10.5  25.0%  $73.095  Total Bond Market: BUY signal
  SHY     HOLD     +8.8  25.0%  $82.370  1-3 Year Treasury: HOLD
  TLT     HOLD     -5.2 100.0%  $85.705  20+ Year Treasury: SELL signal

  Portfolio: $100,000.00 | P&L: +0.000% | Positions: 0 | Win rate: 0.0%
  Next scan in 60s...
```

---

## Architecture

### Data Layer — Two Live Sources

**Alpaca Markets** — real-time bond ETF prices
| ETF | Name | Duration | Risk |
|---|---|---|---|
| TLT | 20+ Year Treasury | Long | High rate sensitivity |
| IEF | 7-10 Year Treasury | Intermediate | Medium rate sensitivity |
| SHY | 1-3 Year Treasury | Short | Low rate sensitivity |
| AGG | US Aggregate Bond | Intermediate | Medium |
| BND | Total Bond Market | Intermediate | Medium |
| HYG | High Yield Corporate | Intermediate | Credit risk |
| LQD | Investment Grade Corporate | Intermediate | Credit risk |

**FRED API (Federal Reserve)** — live macroeconomic data
| Series | What it measures |
|---|---|
| DGS2, DGS5, DGS10, DGS30 | Treasury yields across the curve |
| DFF | Federal Funds Rate |
| T10Y2Y | 10Y-2Y spread (recession indicator) |
| BAMLH0A0HYM2 | High yield credit spread |
| CPIAUCSL | CPI inflation rate |

---

### Algorithm — Four-Signal Fusion

Generates composite bond scores (-100 to +100) by fusing four independent signals:

**Signal 1 — Yield Curve (35% weight)**
Maps curve shape to expected bond performance:
- Inverted curve → rate cuts ahead → long bonds (TLT) favored
- Flat curve → uncertainty → short duration (SHY) optimal
- Normal curve → healthy economy → intermediate bonds balanced

**Signal 2 — Rate Momentum (25% weight)**
Measures direction and velocity of rate changes. Duration multipliers amplify signals appropriately — long bonds (TLT) are 2.5× more sensitive than short bonds (SHY).

**Signal 3 — Credit Spread (20% weight)**
High yield spread analysis for risk-on/risk-off positioning:
- Wide spreads → flight to safety → favor Treasuries, avoid HYG
- Tight spreads → risk appetite → credit bonds attractive

**Signal 4 — Price Momentum (20% weight)**
5-day vs 20-day SMA crossover with mean reversion. Detects overbought/oversold conditions across all ETFs.

**Core bond principle:** Bonds RISE when interest rates FALL. Duration determines sensitivity — a 1% rate move affects TLT ~3× more than SHY.

---

### Security Layer — Enterprise Grade

| Component | What it does |
|---|---|
| `SecureKeyStore` | AES-equivalent encryption of API keys at rest with HMAC authentication |
| `RateLimiter` | Token bucket limits per endpoint — prevents API abuse and runaway costs |
| `CircuitBreaker` | Halts trading on 3+ consecutive losses, API errors, or anomalous signals |
| `TradeValidator` | Validates every trade input before it reaches the algorithm |
| `AuditTrail` | Tamper-evident JSONL log with hash chaining — every trade and signal recorded |

Security test results:
```
✓ Key encryption working
✓ Rate limiter working
✓ Input validation working
✓ Circuit breaker working
✓ Audit trail working

✅ ALL SECURITY TESTS PASSED
```

---

### Portfolio & Risk Management

- **$100,000 paper capital** — no real money until you're ready
- **Max position size:** 25% of portfolio per ETF
- **Max concentration:** 30% in any single ETF
- **Daily loss limit:** halt trading if exceeded
- **Automatic stop/target monitoring** — checks every price update
- **Persistent state** — portfolio survives restarts via JSON
- **Win rate tracking** — running performance metrics

---

## Project Files

| File | Description |
|---|---|
| `bond_data.py` | Alpaca bond ETF quotes + FRED yield curve data feed |
| `bond_algorithm.py` | Four-signal fusion algorithm with position sizing |
| `portfolio.py` | Position tracker, P&L, risk metrics, state persistence |
| `security.py` | Encryption, rate limiting, circuit breaker, audit trail |
| `bond_main.py` | Main orchestrator — runs the full pipeline every 60 seconds |

---

## Setup & Usage

### 1. Install dependency
```bash
pip3 install websockets
```

### 2. Get free API keys

**Alpaca Markets** (already have this from the Market Forensics Engine):
- Sign up free at [alpaca.markets](https://alpaca.markets)
- Settings → API Keys → Generate New Key

**FRED API** (Federal Reserve — completely free):
- Sign up at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html)
- Takes 2 minutes — just fill in a description and agree to terms

### 3. Test security layer first
```bash
python3 security.py
```
Expected: `ALL SECURITY TESTS PASSED`

### 4. Run the platform
```bash
export ALPACA_API_KEY="your_alpaca_key"
export ALPACA_SECRET="your_alpaca_secret"
export FRED_API_KEY="your_fred_key"

python3 bond_main.py
```

The platform scans all 7 bond ETFs every 60 seconds, pulls live yield curve data from the Federal Reserve, runs the four-signal algorithm, and paper-trades any signals above the confidence threshold.

---

## Related Project

This platform is the companion to the **AI Market Forensics Engine** — an equity market manipulation detection system with a novel mean-reversion trading algorithm (Reflexive Momentum Decay).

**→ [github.com/axlAJ/ai-market-forensics-engine](https://github.com/axlAJ/ai-market-forensics-engine)**

Both platforms run simultaneously — one scanning bond markets, one scanning equity manipulation.

---

## Technical Stack

- **Language:** Python 3.11
- **Bond ETF data:** Alpaca Markets REST API
- **Macro data:** Federal Reserve FRED API
- **Key concepts:** Yield curve analysis, duration risk, credit spread analysis, momentum signals, mean reversion, Shannon entropy, token bucket rate limiting, HMAC encryption
- **No external ML libraries** — pure Python signal processing

---

## About

**Philip AJ Sogah** is an AI Innovator, Project Manager, and Software Engineer finishing a BS in Computer Science at Norwich University. Specializing in AI research, forensic technology, financial systems, and algorithmic trading.

- 🌐 [philipajsogah.io](https://philipajsogah.io)
- 📧 philipaxl7@gmail.com
- 📞 +1 802-431-8215
- 🔗 [AI Market Forensics Engine](https://github.com/axlAJ/ai-market-forensics-engine)

---

*Paper trade mode is enabled by default. No real money is used until explicitly configured.*
