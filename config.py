"""
Centralized Configuration
All tuning constants loaded from environment variables with sensible defaults.
Change behaviour without touching code — just update your .env file.
"""
import os
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()


# =============================================================================
# Market Timing
# =============================================================================
MARKET_INTERVAL_SECONDS = int(os.getenv("MARKET_INTERVAL_SECONDS", "900"))   # 15-min markets
RESTART_AFTER_MINUTES = int(os.getenv("RESTART_AFTER_MINUTES", "90"))        # Auto-restart interval

# =============================================================================
# Quote Stability Gate
# =============================================================================
QUOTE_STABILITY_REQUIRED = int(os.getenv("QUOTE_STABILITY_REQUIRED", "3"))   # Valid ticks before stable
QUOTE_MIN_SPREAD = float(os.getenv("QUOTE_MIN_SPREAD", "0.001"))             # Min bid/ask value

# =============================================================================
# Trade Window (seconds into each 15-min interval)
# =============================================================================
TRADE_WINDOW_START = int(os.getenv("TRADE_WINDOW_START", "780"))   # 13 minutes in
TRADE_WINDOW_END = int(os.getenv("TRADE_WINDOW_END", "840"))       # 14 minutes in (60s window)

# =============================================================================
# Trend Filter Thresholds
# =============================================================================
TREND_UP_THRESHOLD = float(os.getenv("TREND_UP_THRESHOLD", "0.60"))     # Price above → buy YES
TREND_DOWN_THRESHOLD = float(os.getenv("TREND_DOWN_THRESHOLD", "0.40")) # Price below → buy NO

# =============================================================================
# Position Sizing
# =============================================================================
POSITION_SIZE_USD = Decimal(os.getenv("POSITION_SIZE_USD", "1.00"))       # Fixed per-trade size
MIN_LIQUIDITY = Decimal(os.getenv("MIN_LIQUIDITY", "0.02"))              # Min bid/ask for order

# =============================================================================
# Signal Fusion
# =============================================================================
FUSION_MIN_SIGNALS = int(os.getenv("FUSION_MIN_SIGNALS", "1"))
FUSION_MIN_SCORE = float(os.getenv("FUSION_MIN_SCORE", "40.0"))

# =============================================================================
# Signal Weights (must sum ≤ 1.0; higher = more influence)
# =============================================================================
SIGNAL_WEIGHTS = {
    "OrderBookImbalance": float(os.getenv("WEIGHT_ORDERBOOK", "0.30")),
    "TickVelocity":       float(os.getenv("WEIGHT_TICK_VELOCITY", "0.25")),
    "PriceDivergence":    float(os.getenv("WEIGHT_DIVERGENCE", "0.18")),
    "SpikeDetection":     float(os.getenv("WEIGHT_SPIKE", "0.12")),
    "DeribitPCR":         float(os.getenv("WEIGHT_DERIBIT_PCR", "0.10")),
    "SentimentAnalysis":  float(os.getenv("WEIGHT_SENTIMENT", "0.05")),
}

# =============================================================================
# Signal Processor Parameters
# =============================================================================
SPIKE_THRESHOLD = float(os.getenv("SPIKE_THRESHOLD", "0.05"))
SPIKE_LOOKBACK = int(os.getenv("SPIKE_LOOKBACK", "20"))

SENTIMENT_FEAR_THRESHOLD = int(os.getenv("SENTIMENT_FEAR_THRESHOLD", "25"))
SENTIMENT_GREED_THRESHOLD = int(os.getenv("SENTIMENT_GREED_THRESHOLD", "75"))

DIVERGENCE_THRESHOLD = float(os.getenv("DIVERGENCE_THRESHOLD", "0.05"))

ORDERBOOK_IMBALANCE_THRESHOLD = float(os.getenv("ORDERBOOK_IMBALANCE_THRESHOLD", "0.30"))
ORDERBOOK_MIN_VOLUME = float(os.getenv("ORDERBOOK_MIN_VOLUME", "50.0"))

TICK_VELOCITY_60S = float(os.getenv("TICK_VELOCITY_60S", "0.015"))
TICK_VELOCITY_30S = float(os.getenv("TICK_VELOCITY_30S", "0.010"))

DERIBIT_BULLISH_PCR = float(os.getenv("DERIBIT_BULLISH_PCR", "1.20"))
DERIBIT_BEARISH_PCR = float(os.getenv("DERIBIT_BEARISH_PCR", "0.70"))
DERIBIT_MAX_DTE = int(os.getenv("DERIBIT_MAX_DTE", "2"))
DERIBIT_CACHE_SECONDS = int(os.getenv("DERIBIT_CACHE_SECONDS", "300"))

# =============================================================================
# Learning Engine
# =============================================================================
LEARNING_RATE = float(os.getenv("LEARNING_RATE", "0.1"))
LEARNING_MIN_TRADES = int(os.getenv("LEARNING_MIN_TRADES", "10"))
LEARNING_TRIGGER_INTERVAL = int(os.getenv("LEARNING_TRIGGER_INTERVAL", "10"))  # Every N trades

# =============================================================================
# Price History
# =============================================================================
# At ~4 ticks/sec: 500 entries ≈ 2+ minutes of history.
# The old value of 100 only covered ~25s, making SMA-20 a near-instant average.
MAX_PRICE_HISTORY = int(os.getenv("MAX_PRICE_HISTORY", "500"))
TICK_BUFFER_SIZE = int(os.getenv("TICK_BUFFER_SIZE", "500"))

# =============================================================================
# Redis
# =============================================================================
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "2"))

# =============================================================================
# Market Slug Pattern (for generalization)
# =============================================================================
MARKET_ASSET = os.getenv("MARKET_ASSET", "btc")
MARKET_TYPE = os.getenv("MARKET_TYPE", "updown")
MARKET_TIMEFRAME = os.getenv("MARKET_TIMEFRAME", "15m")
MARKET_SLUG_PREFIX = f"{MARKET_ASSET}-{MARKET_TYPE}-{MARKET_TIMEFRAME}"

# =============================================================================
# NautilusTrader
# =============================================================================
DATA_ENGINE_QSIZE = int(os.getenv("DATA_ENGINE_QSIZE", "6000"))
EXEC_ENGINE_QSIZE = int(os.getenv("EXEC_ENGINE_QSIZE", "6000"))
TRADER_ID = os.getenv("TRADER_ID", "BTC-15MIN-INTEGRATED-001")
LOG_LEVEL = os.getenv("NAUTILUS_LOG_LEVEL", "INFO")
LOG_DIR = os.getenv("NAUTILUS_LOG_DIR", "./logs/nautilus")
