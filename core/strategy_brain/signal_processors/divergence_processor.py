"""
Price Divergence Signal Processor
Detects when Polymarket UP probability misprices BTC spot momentum

KEY INSIGHT:
  Polymarket "Up" price = probability that BTC will be HIGHER at market close
  Coinbase price       = actual BTC spot price in USD

  These are INCOMPARABLE. Never subtract them.

  Instead, the signal is:
    - Use SPOT MOMENTUM (recent BTC price direction) to predict whether
      "Up" is more or less likely than the current Polymarket probability implies.
    - Use POLYMARKET MISPRICING: if the market heavily favors Up (>0.65) but
      BTC momentum is bearish, bet DOWN. Vice versa.

  Two sub-signals:
  1. MOMENTUM SIGNAL: Is BTC trending up or down over the last ~15 min?
     → metadata['momentum'] is already computed as 5-period ROC of poly prices,
       but we use spot_price vs spot_price_prev if available, else fall back
       to polymarket momentum.

  2. MISPRICING SIGNAL: Is the Polymarket UP probability too extreme vs
     what momentum/sentiment suggest?
     → If poly_price > 0.65 and momentum is bearish → BEARISH (market over-priced Up)
     → If poly_price < 0.35 and momentum is bullish → BULLISH (market over-priced Down)
     → If poly_price near 0.50, no strong edge → skip
"""
from decimal import Decimal
from datetime import datetime
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


class PriceDivergenceProcessor(BaseSignalProcessor):
    """
    Detects mispricings between Polymarket UP probability and BTC spot momentum.

    Replaces the broken "compare probability to dollar price" approach with two
    meaningful signals:

    1. MOMENTUM MISPRICING:
       If BTC spot is trending UP strongly but Polymarket "Up" probability is
       below 0.50, the market is underpricing the move → BUY UP.
       Vice versa for downtrend.

    2. EXTREME PROBABILITY FADE:
       If Polymarket "Up" is priced above 0.70, it's unlikely to resolve even
       higher — fade toward DOWN. If below 0.30, fade toward UP.
       (Markets rarely sustain >70% probability at interval open.)
    """

    def __init__(
        self,
        divergence_threshold: float = 0.05,   # kept for API compatibility (unused)
        min_confidence: float = 0.55,
        momentum_threshold: float = 0.003,     # 0.3% spot move = meaningful momentum
        extreme_prob_threshold: float = 0.68,  # above this → fade to Down
        low_prob_threshold: float = 0.32,      # below this → fade to Up
    ):
        super().__init__("PriceDivergence")

        self.min_confidence = min_confidence
        self.momentum_threshold = momentum_threshold
        self.extreme_prob_threshold = extreme_prob_threshold
        self.low_prob_threshold = low_prob_threshold

        # Rolling spot price history for momentum calculation
        self._spot_history: List[float] = []
        self._max_spot_history = 10  # last 10 readings (~2.5 min of data)

        logger.info(
            f"Initialized Price Divergence Processor (FIXED): "
            f"momentum_thresh={momentum_threshold:.1%}, "
            f"extreme_fade={extreme_prob_threshold:.0%}/{low_prob_threshold:.0%}"
        )

    def process(
        self,
        current_price: Decimal,      # Polymarket UP probability (0.0–1.0)
        historical_prices: list,
        metadata: Dict[str, Any] = None,
    ) -> Optional[TradingSignal]:
        """
        Generate signal from spot momentum vs Polymarket probability.

        metadata keys used:
          - spot_price (float): current Coinbase BTC-USD price
          - momentum (float): pre-computed 5-period ROC of polymarket prices
        """
        if not self.is_enabled:
            return None

        if not metadata:
            return None

        poly_prob = float(current_price)  # e.g. 0.49 = 49% chance BTC goes Up

        spot_price = metadata.get('spot_price')
        poly_momentum = float(metadata.get('momentum', 0.0))

        # --- Update spot price history for momentum ---
        if spot_price is not None:
            self._spot_history.append(float(spot_price))
            if len(self._spot_history) > self._max_spot_history:
                self._spot_history.pop(0)

        # --- Compute spot momentum ---
        spot_momentum = 0.0
        if spot_price is not None and len(self._spot_history) >= 3:
            # Compare latest spot to 3 readings ago
            oldest = self._spot_history[-min(3, len(self._spot_history))]
            spot_momentum = (float(spot_price) - oldest) / oldest
        elif spot_price is None:
            # Fall back to polymarket price momentum if no spot available
            spot_momentum = poly_momentum

        logger.info(
            f"PriceDivergence: poly_prob={poly_prob:.3f}, "
            f"spot_momentum={spot_momentum:+.4f} ({spot_momentum*100:+.2f}%), "
            f"spot_price={'${:,.2f}'.format(spot_price) if spot_price else 'N/A'}"
        )

        # =====================================================================
        # SIGNAL 1: EXTREME PROBABILITY FADE
        # If the market has already priced in a strong move, fade it.
        # =====================================================================
        if poly_prob >= self.extreme_prob_threshold:
            # Market >68% confident BTC goes Up — but at interval open this
            # is extreme and tends to revert. Fade to DOWN unless momentum
            # strongly confirms the move.
            if spot_momentum <= 0.001:  # momentum not strongly confirming Up
                extremeness = (poly_prob - self.extreme_prob_threshold) / (1.0 - self.extreme_prob_threshold)
                confidence = min(0.80, self.min_confidence + extremeness * 0.25)
                strength = SignalStrength.STRONG if extremeness > 0.5 else SignalStrength.MODERATE

                signal = TradingSignal(
                    timestamp=datetime.now(),
                    source=self.name,
                    signal_type=SignalType.PRICE_DIVERGENCE,
                    direction=SignalDirection.BEARISH,
                    strength=strength,
                    confidence=confidence,
                    current_price=current_price,
                    metadata={
                        "signal_type": "extreme_prob_fade_down",
                        "poly_prob": poly_prob,
                        "spot_momentum": spot_momentum,
                        "extremeness": extremeness,
                    }
                )
                self._record_signal(signal)
                logger.info(
                    f"Generated BEARISH fade signal: poly Up prob too high "
                    f"({poly_prob:.0%}) with weak momentum → fade DOWN, "
                    f"confidence={confidence:.2%}"
                )
                return signal

        elif poly_prob <= self.low_prob_threshold:
            # Market >68% confident BTC goes Down — fade to UP unless momentum confirms
            if spot_momentum >= -0.001:  # not strongly falling
                extremeness = (self.low_prob_threshold - poly_prob) / self.low_prob_threshold
                confidence = min(0.80, self.min_confidence + extremeness * 0.25)
                strength = SignalStrength.STRONG if extremeness > 0.5 else SignalStrength.MODERATE

                signal = TradingSignal(
                    timestamp=datetime.now(),
                    source=self.name,
                    signal_type=SignalType.PRICE_DIVERGENCE,
                    direction=SignalDirection.BULLISH,
                    strength=strength,
                    confidence=confidence,
                    current_price=current_price,
                    metadata={
                        "signal_type": "extreme_prob_fade_up",
                        "poly_prob": poly_prob,
                        "spot_momentum": spot_momentum,
                        "extremeness": extremeness,
                    }
                )
                self._record_signal(signal)
                logger.info(
                    f"Generated BULLISH fade signal: poly Down prob too high "
                    f"({1-poly_prob:.0%}) with weak negative momentum → fade UP, "
                    f"confidence={confidence:.2%}"
                )
                return signal

        # =====================================================================
        # SIGNAL 2: MOMENTUM MISPRICING
        # Polymarket probability near 50% but spot has strong directional move.
        # The market hasn't priced in the momentum yet → trade with momentum.
        # Only fires when poly_prob is between 35-65% (no strong lean already).
        # =====================================================================
        if 0.35 <= poly_prob <= 0.65 and abs(spot_momentum) >= self.momentum_threshold:
            # Strong spot momentum but Polymarket still near 50/50 → edge
            momentum_strength = abs(spot_momentum) / self.momentum_threshold  # multiplier
            confidence = min(0.78, 0.55 + min(momentum_strength - 1, 2) * 0.08)
            
            if momentum_strength >= 3:
                strength = SignalStrength.STRONG
            elif momentum_strength >= 2:
                strength = SignalStrength.MODERATE
            else:
                strength = SignalStrength.WEAK

            if confidence < self.min_confidence:
                return None

            direction = SignalDirection.BULLISH if spot_momentum > 0 else SignalDirection.BEARISH

            signal = TradingSignal(
                timestamp=datetime.now(),
                source=self.name,
                signal_type=SignalType.PRICE_DIVERGENCE,
                direction=direction,
                strength=strength,
                confidence=confidence,
                current_price=current_price,
                metadata={
                    "signal_type": "momentum_mispricing",
                    "poly_prob": poly_prob,
                    "spot_momentum": spot_momentum,
                    "momentum_strength": momentum_strength,
                }
            )
            self._record_signal(signal)
            logger.info(
                f"Generated {direction.value.upper()} momentum signal: "
                f"spot moved {spot_momentum:+.3%} but poly still at {poly_prob:.0%}, "
                f"confidence={confidence:.2%}"
            )
            return signal

        logger.debug(
            f"PriceDivergence: no signal — prob={poly_prob:.2f}, "
            f"momentum={spot_momentum:+.4f} (below threshold or already priced in)"
        )
        return None
