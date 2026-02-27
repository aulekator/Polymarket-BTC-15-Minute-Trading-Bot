"""
Paper trading simulation logic.

Extracted from bot.py to reduce monolithic file size.
These functions are mixed into IntegratedBTCStrategy via import.
"""
import json
import random
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from loguru import logger

from models import PaperTrade
import config as cfg


async def record_paper_trade(strategy, signal, position_size, current_price, direction):
    """
    Record a simulated trade with realistic binary-outcome model.

    Polymarket 15-min markets resolve to 1.00 (UP wins) or 0.00 (DOWN wins).
    The current price IS the market's probability of UP resolution:
      Price = 0.72 → 72% chance resolves UP (YES=1.00, NO=0.00)
      Price = 0.35 → 35% chance resolves UP (65% chance DOWN wins)
    """
    exit_delta = timedelta(minutes=1) if strategy.test_mode else timedelta(minutes=15)
    exit_time = datetime.now(timezone.utc) + exit_delta

    price_float = float(current_price)
    up_probability = price_float  # The price IS the probability

    # Simulate whether BTC actually went UP
    btc_went_up = random.random() < up_probability

    if btc_went_up:
        exit_price = Decimal("1.00")  # YES resolves to 1.00
    else:
        exit_price = Decimal("0.00")  # YES resolves to 0.00

    # Calculate P&L based on direction
    if direction == "long":
        # Bought YES at current_price
        pnl = position_size * (exit_price - current_price) / current_price
    else:
        # Bought NO — equivalent to shorting YES from 1.00
        no_entry = Decimal("1.00") - current_price
        no_exit = Decimal("1.00") - exit_price
        pnl = position_size * (no_exit - no_entry) / no_entry if no_entry > 0 else Decimal("0")

    outcome = "WIN" if pnl > 0 else "LOSS"
    paper_trade = PaperTrade(
        timestamp=datetime.now(timezone.utc),
        direction=direction.upper(),
        size_usd=float(position_size),
        price=float(current_price),
        signal_score=signal.score,
        signal_confidence=signal.confidence,
        outcome=outcome,
    )
    strategy.paper_trades.append(paper_trade)

    strategy.performance_tracker.record_trade(
        trade_id=f"paper_{int(datetime.now().timestamp())}",
        direction=direction,
        entry_price=current_price,
        exit_price=exit_price,
        size=position_size,
        entry_time=datetime.now(timezone.utc),
        exit_time=exit_time,
        signal_score=signal.score,
        signal_confidence=signal.confidence,
        metadata={
            "simulated": True,
            "num_signals": signal.num_signals if hasattr(signal, 'num_signals') else 1,
            "fusion_score": signal.score,
        }
    )

    if hasattr(strategy, 'grafana_exporter') and strategy.grafana_exporter:
        strategy.grafana_exporter.increment_trade_counter(won=(pnl > 0))
        strategy.grafana_exporter.record_trade_duration(exit_delta.total_seconds())

    logger.info("=" * 80)
    logger.info("[SIMULATION] PAPER TRADE RECORDED")
    logger.info(f"  Direction: {direction.upper()}")
    logger.info(f"  Size: ${float(position_size):.2f}")
    logger.info(f"  Entry Price: ${float(current_price):,.4f}")
    logger.info(f"  Resolution: {'UP (YES→1.00)' if btc_went_up else 'DOWN (YES→0.00)'}")
    logger.info(f"  P&L: ${float(pnl):+.4f}")
    logger.info(f"  Outcome: {outcome}")
    logger.info(f"  Total Paper Trades: {len(strategy.paper_trades)}")
    logger.info("=" * 80)

    save_paper_trades(strategy)

    # --- Phase 7: Trigger learning engine every N trades ---
    strategy._trade_count += 1
    if strategy._trade_count % cfg.LEARNING_TRIGGER_INTERVAL == 0:
        try:
            new_weights = await strategy.learning_engine.optimize_weights()
            if new_weights:
                logger.info(f"Learning engine updated weights after {strategy._trade_count} trades")
        except Exception as e:
            logger.warning(f"Learning engine optimization failed: {e}")


def save_paper_trades(strategy):
    """Save paper trades to JSON file."""
    try:
        trades_data = [t.to_dict() for t in strategy.paper_trades]
        with open('paper_trades.json', 'w') as f:
            json.dump(trades_data, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save paper trades: {e}")
