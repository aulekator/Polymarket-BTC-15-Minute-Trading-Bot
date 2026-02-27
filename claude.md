# CLAUDE.md — Polymarket BTC 15-Min Trading Bot

## Project Overview

Production-grade algorithmic trading bot for **Polymarket's 15-minute BTC price prediction markets**. Built on NautilusTrader (v1.222.0), it uses a 7-phase architecture: data ingestion → nautilus integration → signal processing → signal fusion → risk management → order execution → monitoring/learning.

**Key trading logic**: trades in the **13–14 minute window** of each 15-minute market. At that point the Polymarket price _is_ the trend — prices > 0.60 → buy YES, < 0.40 → buy NO, 0.40–0.60 → skip. Fixed position size of $1.00 per trade.

## Quick Reference

| Command | Purpose |
|---------|---------|
| `python runner.py --test-mode` | Simulation, 1-min intervals (preferred) |
| `python runner.py` | Simulation, 15-min intervals |
| `python runner.py --live` | **LIVE TRADING — real money** |
| `python runner.py --no-grafana` | Disable Grafana metrics |
| `python bot.py` | Backward-compatible entry (delegates to runner.py) |
| `python view_paper_trades.py` | View simulation trades |
| `python redis_control.py sim/live` | Switch mode (use with caution) |

## Architecture

```
bot.py (IntegratedBTCStrategy — core strategy, ~1050 lines)
├── config.py               # All tuning constants — overridable via .env
├── models.py               # PaperTrade dataclass
├── paper_trading.py        # Simulation trade recording and saving
├── runner.py               # CLI entry point, NautilusTrader setup, init_redis
├── core/
│   ├── ingestion/          # Phase 2: adapters, managers, validators
│   ├── nautilus_core/      # Phase 3: data engine, events, instruments, providers
│   └── strategy_brain/     # Phase 4: signal processors, fusion engine, strategies
├── data_sources/           # Phase 1: Binance, Coinbase, News/Social, Solana
├── execution/              # Phase 5: execution_engine, polymarket_client, risk_engine
├── monitoring/             # Phase 6: grafana_exporter, performance_tracker
├── feedback/               # Phase 7: learning_engine (with persistent state)
└── grafana/                # Dashboard configs + import script
```

## Key Patterns & Conventions

### Singleton Pattern
Most engines use module-level singletons via `get_*()` factory functions:
- `get_fusion_engine()`, `get_risk_engine()`, `get_performance_tracker()`
- `get_grafana_exporter()`, `get_learning_engine()`, `get_execution_engine()`
- `get_coinbase_source()`, `get_news_social_source()`

When adding new engines or processors, follow this pattern.

### Signal Processor Pattern
All signal processors inherit from `BaseSignalProcessor` (in `core/strategy_brain/signal_processors/base_processor.py`) and implement:
```python
def process(self, current_price: Decimal, historical_prices: list[Decimal], metadata: Dict[str, Any]) -> Optional[TradingSignal]
```
Signals carry `direction` (BULLISH/BEARISH/NEUTRAL), `strength` (1-4), and `confidence` (0.0-1.0). The fusion engine combines them via weighted voting.

### Active signal processors (6):
| Processor | Weight | Source |
|-----------|--------|--------|
| OrderBookImbalance | 0.30 | Polymarket CLOB depth |
| TickVelocity | 0.25 | Last 60s Polymarket price movement |
| PriceDivergence | 0.18 | Coinbase spot vs Polymarket price |
| SpikeDetection | 0.12 | Price spike / mean-reversion |
| DeribitPCR | 0.10 | Deribit options put/call ratio |
| SentimentAnalysis | 0.05 | Fear & Greed Index |

### Data Flow
1. Quote ticks arrive via NautilusTrader WebSocket → `on_quote_tick()`
2. Prices stored in `self.price_history` (`deque(maxlen=100)`)
3. At minutes 13–14 (configurable via `TRADE_WINDOW_START/END`), `_make_trading_decision()` fires
4. External data fetched **in parallel** via `asyncio.gather` (Coinbase spot + Fear & Greed)
5. 6 signal processors run → fusion → trend filter → risk check → order

### Async/Sync Boundary
NautilusTrader callbacks are synchronous. Trading decisions run in an executor via `self.run_in_executor()`, which uses a **persistent asyncio event loop** (one per strategy instance). External HTTP calls use `httpx` with pooled clients.

### Market Lifecycle
Markets are loaded at startup via slug-based filters (e.g., `btc-updown-15m-{timestamp}`). The bot auto-switches between markets when each 15-min interval ends and auto-restarts after 90 minutes.

## Dependencies

- **NautilusTrader 1.222.0** — core trading framework with Polymarket adapter
- **Redis** — dynamic sim/live mode switching
- **httpx** — async HTTP for data sources
- **prometheus_client** — Grafana metrics
- **py-clob-client** — Polymarket CLOB API
- **loguru** — structured logging
- **python-dotenv** — env config

### NautilusTrader: Trade-offs

NautilusTrader is a **professional-grade, Rust/Cython-backed** trading framework with a built-in Polymarket adapter — this is the primary reason it's used. Its advantages:
- Built-in WebSocket management, instrument caching, order lifecycle, and risk engine
- Event-driven architecture handles tick data efficiently
- The Polymarket adapter (data + execution) saves hundreds of lines of custom integration

**However**, it's arguably **overkill** for this use case:
- The bot trades **once every 15 minutes** — NautilusTrader is designed for microsecond-latency HFT
- Two monkey patches (`patch_gamma_markets.py`, `patch_market_orders.py`) are required, suggesting the Polymarket adapter has gaps
- The `run_in_executor()` + new asyncio event loop pattern adds overhead that wouldn't exist in a simpler design
- NautilusTrader's queue sizes (6000) and full data/exec engine infrastructure consume memory for a bot that processes ~4 ticks/second

**Alternatives to consider** (if maintenance burden of patches becomes unsustainable):
- Direct `py-clob-client` + `websockets` — simpler, fewer deps, no patches needed
- `ccxt` for Coinbase/Binance + direct Polymarket CLOB — lighter stack

**Recommendation**: Keep NautilusTrader for now — the adapter and infrastructure work. But if a NautilusTrader upgrade breaks the patches, consider migrating to a direct CLOB integration.

## Configuration

All tuning constants live in `config.py` and are loaded from `.env` with sensible defaults.

Required in `.env`:
```
# Polymarket API (required for live trading)
POLYMARKET_PK, POLYMARKET_API_KEY, POLYMARKET_API_SECRET, POLYMARKET_PASSPHRASE
MARKET_BUY_USD  # max USD per order (used by market order patch)
```

Optional overrides (see `config.py` for full list):
```
# Trade timing
TRADE_WINDOW_START=780        # seconds into 15-min interval
TRADE_WINDOW_END=840

# Trend filter
TREND_UP_THRESHOLD=0.60
TREND_DOWN_THRESHOLD=0.40

# Position sizing
POSITION_SIZE_USD=1.00

# Signal weights (must sum ≤ 1.0)
WEIGHT_ORDERBOOK=0.30
WEIGHT_TICK_VELOCITY=0.25
WEIGHT_DIVERGENCE=0.18
WEIGHT_SPIKE=0.12
WEIGHT_DERIBIT_PCR=0.10
WEIGHT_SENTIMENT=0.05

# Market generalization
MARKET_ASSET=btc
MARKET_TIMEFRAME=15m

# NautilusTrader
TRADER_ID=BTC-15MIN-INTEGRATED-001
DATA_ENGINE_QSIZE=6000
NAUTILUS_LOG_LEVEL=INFO
```

## Patches

Two monkey-patches are applied at import time:
- `patch_gamma_markets.py` — fixes Polymarket gamma market instrument loading
- `patch_market_orders.py` — converts market orders to USD-denominated FAK orders

These **must** succeed or the bot exits. If NautilusTrader is updated, these patches may need adjustment.

## Testing

Tests are per-phase, run independently:
```bash
python data_sources/test.py
python core/ingestion/test_ingestion.py
python core/nautilus_core/test_nautilus.py
python core/strategy_brain/test_strategy.py
python execution/test_execution.py
python test.py  # top-level integration test
```

## Debugging Tips

- Logs go to `./logs/nautilus/` and stdout via loguru
- Paper trades saved to `paper_trades.json`
- Grafana metrics at `http://localhost:8000/metrics`
- Use `--test-mode` for 1-minute fast clock
- If orders are rejected with "no orders found" or "FAK", it means no matching liquidity — the bot auto-retries on next tick

## Known Issues & Technical Debt

1. ~~**Duplicate method**~~ ✅ Fixed
2. ~~**Data source reconnection**~~ ✅ Fixed — singletons + parallel fetch
3. ~~**O(n) price history**~~ ✅ Fixed — `deque(maxlen=100)`
4. ~~**httpx client churn**~~ ✅ Fixed — pooled clients
5. ~~**Stability gate bypassed**~~ ✅ Fixed
6. ~~**Learning engine dead code**~~ ✅ Fixed — optimizes every 10 trades + persistent state
7. ~~**Event loop churn**~~ ✅ Fixed — persistent loop
8. ~~**Tuning constants hardcoded**~~ ✅ Fixed — all in `config.py`
9. ~~**Monolithic bot.py**~~ ✅ Fixed — decomposed into `models.py`, `paper_trading.py`, `runner.py`, `config.py`
10. ~~**Redis async/sync mismatch**~~ ✅ Fixed — `check_simulation_mode()` is now sync
11. ~~**Paper trade P&L random**~~ ✅ Fixed — uses binary-outcome probability model
12. ~~**No persistent learning state**~~ ✅ Fixed — `learning_state.json` save/load
13. **`redis_control.py`** — works but live mode switching mid-run may cause issues
