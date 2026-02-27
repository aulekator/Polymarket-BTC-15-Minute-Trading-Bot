"""
Tick Velocity Signal Processor
Measures how fast the Polymarket UP probability is moving in the
last 60 seconds before the trade window opens.

WHY THIS WORKS:
  If the "Up" probability moves from 0.50 → 0.57 in the last 45 seconds,
  BEFORE your bot even looks at it, that reflects real order flow from
  other traders reacting to BTC spot movement. The probability is being
  pushed by real money, and it often continues in the same direction
  for at least another 30–60 seconds.

  This is "price action" on the Polymarket itself — not a lagging
  external indicator. It's the most direct signal available.

HOW IT WORKS:
  The strategy stores a rolling tick buffer:
    self._tick_buffer = deque of {'ts': datetime, 'price': Decimal}

  This processor receives that buffer via metadata['tick_buffer'].

  It computes:
    1. 60s velocity  = (now_price - price_60s_ago) / price_60s_ago
    2. 30s velocity  = (now_price - price_30s_ago) / price_30s_ago
    3. Acceleration  = 30s_velocity - (60s_velocity - 30s_velocity)
                       (is it speeding up or slowing down?)

  Signal thresholds (for 0–1 probability prices):
    velocity > +1.5%  in 60s → BULLISH
    velocity < -1.5%  in 60s → BEARISH
    acceleration bonus: if move is accelerating → higher confidence

INTEGRATION:
  In bot.py on_quote_tick(), add:
    self._tick_buffer.append({'ts': now, 'price': mid_price})

  In _fetch_market_context(), add:
    metadata['tick_buffer'] = list(self._tick_buffer)
"""
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from collections import deque
from typing import Optional, Dict, Any, List
from loguru import logger

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.strategy_brain.signal_processors.base_processor import (
    BaseSignalProcessor,
    TradingSignal,
    SignalType,
    SignalDirection,
    SignalStrength,
)


class TickVelocityProcessor(BaseSignalProcessor):
    """
    Measures Polymarket probability velocity over the last 60 seconds.

    Fast moves in probability = real order flow = tradeable signal.
    """

    def __init__(
        self,
        velocity_threshold_60s: float = 0.015,   # 1.5% move in 60s
        velocity_threshold_30s: float = 0.010,   # 1.0% move in 30s
        min_ticks: int = 5,                       # need at least 5 ticks in window
        min_confidence: float = 0.55,
    ):
        super().__init__("TickVelocity")

        self.velocity_threshold_60s = velocity_threshold_60s
        self.velocity_threshold_30s = velocity_threshold_30s
        self.min_ticks = min_ticks
        self.min_confidence = min_confidence

        logger.info(
            f"Initialized Tick Velocity Processor: "
            f"60s_threshold={velocity_threshold_60s:.1%}, "
            f"30s_threshold={velocity_threshold_30s:.1%}"
        )

    def _get_price_at(
        self,
        tick_buffer,
        seconds_ago: float,
        now: datetime,
    ) -> Optional[float]:
        """
        Find the tick price closest to `seconds_ago` seconds before now.

        Optimized: iterates backward (newest first) and stops early once
        past the target window. O(k) where k = ticks in lookback window.
        """
        target = now - timedelta(seconds=seconds_ago)
        best = None
        best_diff = 15.0  # max tolerance in seconds

        # Iterate backward — buffer is time-ordered, newest at end
        for i in range(len(tick_buffer) - 1, -1, -1):
            tick = tick_buffer[i]
            ts = tick['ts']
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            diff = abs((ts - target).total_seconds())
            if diff < best_diff:
                best_diff = diff
                best = tick['price']  # already float after C3 fix
            # If we've gone more than 15s past the target, stop
            elif (target - ts).total_seconds() > 15:
                break

        return best if best_diff <= 15.0 else None

    def process(
        self,
        current_price: Decimal,
        historical_prices: list,
        metadata: Dict[str, Any] = None,
    ) -> Optional[TradingSignal]:
        if not self.is_enabled or not metadata:
            return None

        tick_buffer = metadata.get("tick_buffer")
        if not tick_buffer or len(tick_buffer) < self.min_ticks:
            logger.debug(
                f"TickVelocity: insufficient ticks "
                f"({len(tick_buffer) if tick_buffer else 0} < {self.min_ticks})"
            )
            return None

        now = datetime.now(timezone.utc)
        curr = float(current_price)

        # Get historical prices from the buffer
        price_60s = self._get_price_at(tick_buffer, 60, now)
        price_30s = self._get_price_at(tick_buffer, 30, now)

        if price_60s is None and price_30s is None:
            logger.debug("TickVelocity: no historical ticks in 60s window")
            return None

        # Compute velocities
        vel_60s = ((curr - price_60s) / price_60s) if price_60s else None
        vel_30s = ((curr - price_30s) / price_30s) if price_30s else None

        # Compute acceleration (is the move speeding up?)
        acceleration = 0.0
        if vel_60s is not None and vel_30s is not None:
            # First half velocity = 60s vel - 30s vel (approximation)
            vel_first_30s = vel_60s - vel_30s
            acceleration = vel_30s - vel_first_30s  # positive = accelerating

        logger.info(
            f"TickVelocity: curr={curr:.4f}, "
            f"vel_60s={vel_60s*100:+.3f}% " if vel_60s else "vel_60s=N/A "
            f"vel_30s={vel_30s*100:+.3f}% " if vel_30s else "vel_30s=N/A "
            f"accel={acceleration*100:+.4f}%"
        )

        # Use best available velocity for signal decision
        primary_vel = vel_30s if vel_30s is not None else vel_60s
        threshold = (
            self.velocity_threshold_30s if vel_30s is not None
            else self.velocity_threshold_60s
        )

        if abs(primary_vel) < threshold:
            logger.debug(
                f"TickVelocity: {primary_vel*100:+.3f}% below threshold "
                f"{threshold*100:.1f}% — no signal"
            )
            return None

        direction = SignalDirection.BULLISH if primary_vel > 0 else SignalDirection.BEARISH
        abs_vel = abs(primary_vel)

        # Strength by velocity magnitude
        if abs_vel >= 0.04:      # >4%
            strength = SignalStrength.VERY_STRONG
        elif abs_vel >= 0.025:   # >2.5%
            strength = SignalStrength.STRONG
        elif abs_vel >= 0.015:   # >1.5%
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK

        # Base confidence
        confidence = min(0.82, 0.55 + (abs_vel / threshold - 1) * 0.12)

        # Acceleration bonus: if move is accelerating, higher confidence
        accel_same_direction = (
            (acceleration > 0 and primary_vel > 0) or
            (acceleration < 0 and primary_vel < 0)
        )
        if accel_same_direction and abs(acceleration) > 0.005:
            confidence = min(0.88, confidence + 0.06)
            logger.info(f"TickVelocity: acceleration bonus applied ({acceleration*100:+.4f}%)")

        # If 60s velocity conflicts with 30s velocity — reduce confidence
        if vel_60s is not None and vel_30s is not None:
            if (vel_60s > 0) != (vel_30s > 0):
                confidence *= 0.80
                logger.info("TickVelocity: velocity reversal — confidence reduced")

        if confidence < self.min_confidence:
            return None

        signal = TradingSignal(
            timestamp=datetime.now(),
            source=self.name,
            signal_type=SignalType.MOMENTUM,
            direction=direction,
            strength=strength,
            confidence=confidence,
            current_price=current_price,
            metadata={
                "velocity_60s": round(vel_60s, 6) if vel_60s else None,
                "velocity_30s": round(vel_30s, 6) if vel_30s else None,
                "acceleration": round(acceleration, 6),
                "price_60s_ago": round(price_60s, 6) if price_60s else None,
                "price_30s_ago": round(price_30s, 6) if price_30s else None,
                "ticks_in_buffer": len(tick_buffer),
            }
        )

        self._record_signal(signal)

        logger.info(
            f"Generated {direction.value.upper()} signal (TickVelocity): "
            f"vel={primary_vel*100:+.3f}%, accel={acceleration*100:+.4f}%, "
            f"confidence={confidence:.2%}, score={signal.score:.1f}"
        )

        return signal