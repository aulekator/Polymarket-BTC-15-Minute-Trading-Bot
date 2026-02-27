"""
Bot runner — NautilusTrader node setup, slug generation, and main() entry point.

Extracted from bot.py to separate infrastructure from strategy.
"""
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

from loguru import logger
from dotenv import load_dotenv
import redis

load_dotenv()

# Add project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from nautilus_trader.config import (
    InstrumentProviderConfig,
    LiveDataEngineConfig,
    LiveExecEngineConfig,
    LiveRiskEngineConfig,
    LoggingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode
from nautilus_trader.adapters.polymarket import POLYMARKET
from nautilus_trader.adapters.polymarket import (
    PolymarketDataClientConfig,
    PolymarketExecClientConfig,
)
from nautilus_trader.adapters.polymarket.factories import (
    PolymarketLiveDataClientFactory,
    PolymarketLiveExecClientFactory,
)

import config as cfg


def init_redis():
    """Initialize Redis connection for simulation mode control."""
    try:
        redis_client = redis.Redis(
            host=cfg.REDIS_HOST,
            port=cfg.REDIS_PORT,
            db=cfg.REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True
        )
        redis_client.ping()
        logger.info("Redis connection established")
        return redis_client
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        logger.warning("Simulation mode will be static (from .env)")
        return None


def run_integrated_bot(simulation: bool = False, enable_grafana: bool = True, test_mode: bool = False):
    """Run the integrated BTC 15-min trading bot — LOADS ALL BTC MARKETS FOR THE DAY"""
    # Lazy import to avoid circular dependency at module load
    from bot import IntegratedBTCStrategy

    print("=" * 80)
    print("INTEGRATED POLYMARKET BTC 15-MIN TRADING BOT")
    print("Nautilus + 7-Phase System + Redis Control")
    print("=" * 80)

    redis_client = init_redis()

    if redis_client:
        try:
            # ALWAYS overwrite Redis with the current session mode.
            mode_value = '1' if simulation else '0'
            redis_client.set('btc_trading:simulation_mode', mode_value)
            mode_label = 'SIMULATION' if simulation else 'LIVE'
            logger.info(f"Redis simulation_mode forced to: {mode_label} ({mode_value})")
        except Exception as e:
            logger.warning(f"Could not set Redis simulation mode: {e}")

    print(f"\nConfiguration:")
    print(f"  Initial Mode: {'SIMULATION' if simulation else 'LIVE TRADING'}")
    print(f"  Redis Control: {'Enabled' if redis_client else 'Disabled'}")
    print(f"  Grafana: {'Enabled' if enable_grafana else 'Disabled'}")
    print(f"  Max Trade Size: ${os.getenv('MARKET_BUY_USD', '1.00')}")
    print(f"  Quote stability gate: {cfg.QUOTE_STABILITY_REQUIRED} valid ticks")
    print()

    # =========================================================================
    # Slug timestamps ARE standard Unix timestamps aligned to 15-min boundaries.
    # Generate slugs for current + next 24 hours.
    # =========================================================================
    now = datetime.now(timezone.utc)
    unix_interval_start = (int(now.timestamp()) // 900) * 900

    btc_slugs = []
    for i in range(-1, 97):  # include 1 prior interval
        timestamp = unix_interval_start + (i * 900)
        btc_slugs.append(f"{cfg.MARKET_SLUG_PREFIX}-{timestamp}")

    filters = {
        "active": True,
        "closed": False,
        "archived": False,
        "slug": tuple(btc_slugs),
        "limit": 100,
    }

    logger.info("=" * 80)
    logger.info("LOADING BTC 15-MIN MARKETS BY SLUG")
    logger.info(f"  Interval start: {unix_interval_start} | Count: {len(btc_slugs)}")
    logger.info(f"  First: {btc_slugs[0]}  Last: {btc_slugs[-1]}")
    logger.info("=" * 80)

    instrument_cfg = InstrumentProviderConfig(
        load_all=True,
        filters=filters,
        use_gamma_markets=True,
    )

    poly_data_cfg = PolymarketDataClientConfig(
        private_key=os.getenv("POLYMARKET_PK"),
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        passphrase=os.getenv("POLYMARKET_PASSPHRASE"),
        signature_type=1,
        instrument_provider=instrument_cfg,
    )

    poly_exec_cfg = PolymarketExecClientConfig(
        private_key=os.getenv("POLYMARKET_PK"),
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        passphrase=os.getenv("POLYMARKET_PASSPHRASE"),
        signature_type=1,
        instrument_provider=instrument_cfg,
    )

    config = TradingNodeConfig(
        environment="live",
        trader_id=cfg.TRADER_ID,
        logging=LoggingConfig(
            log_level=cfg.LOG_LEVEL,
            log_directory=cfg.LOG_DIR,
        ),
        data_engine=LiveDataEngineConfig(qsize=cfg.DATA_ENGINE_QSIZE),
        exec_engine=LiveExecEngineConfig(qsize=cfg.EXEC_ENGINE_QSIZE),
        risk_engine=LiveRiskEngineConfig(bypass=simulation),
        data_clients={POLYMARKET: poly_data_cfg},
        exec_clients={POLYMARKET: poly_exec_cfg},
    )

    strategy = IntegratedBTCStrategy(
        redis_client=redis_client,
        enable_grafana=enable_grafana,
        test_mode=test_mode,
    )

    print("\nBuilding Nautilus node...")
    node = TradingNode(config=config)
    node.add_data_client_factory(POLYMARKET, PolymarketLiveDataClientFactory)
    node.add_exec_client_factory(POLYMARKET, PolymarketLiveExecClientFactory)
    node.trader.add_strategy(strategy)
    node.build()
    logger.info("Nautilus node built successfully")

    print()
    print("=" * 80)
    print("BOT STARTING")
    print("=" * 80)

    try:
        node.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        node.dispose()
        logger.info("Bot stopped")


def main():
    parser = argparse.ArgumentParser(description="Integrated BTC 15-Min Trading Bot")
    parser.add_argument("--live", action="store_true",
                        help="Run in LIVE mode (real money at risk!). Default is simulation.")
    parser.add_argument("--no-grafana", action="store_true", help="Disable Grafana metrics")
    parser.add_argument("--test-mode", action="store_true",
                        help="Run in TEST MODE (trade every minute for faster testing)")

    args = parser.parse_args()
    enable_grafana = not args.no_grafana
    test_mode = args.test_mode

    # --test-mode ALWAYS forces simulation even if --live is also passed
    if args.test_mode:
        simulation = True
    else:
        simulation = not args.live

    if not simulation:
        logger.warning("=" * 80)
        logger.warning("LIVE TRADING MODE — REAL MONEY AT RISK!")
        logger.warning("=" * 80)
    else:
        logger.info("=" * 80)
        logger.info(f"SIMULATION MODE — {'TEST MODE (fast clock)' if test_mode else 'paper trading only'}")
        logger.info("No real orders will be placed.")
        logger.info("=" * 80)

    run_integrated_bot(simulation=simulation, enable_grafana=enable_grafana, test_mode=test_mode)


if __name__ == "__main__":
    main()
