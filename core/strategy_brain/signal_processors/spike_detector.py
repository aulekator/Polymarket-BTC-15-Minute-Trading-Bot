"""
Spike Detection Signal Processor
Detects sudden price movements and generates mean reversion signals
"""
from decimal import Decimal
from datetime import datetime
from typing import Optional, Dict, Any
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


class SpikeDetectionProcessor(BaseSignalProcessor):
    """
    Detects price spikes and generates mean reversion signals.
    
    Logic:
    1. Calculate moving average from historical prices
    2. Detect when current price deviates significantly
    3. Generate counter-trend signal (fade the spike)
    4. Calculate confidence based on spike magnitude
    """
    
    def __init__(
        self,
        spike_threshold: float = 0.15,  # 15% deviation
        lookback_periods: int = 20,
        min_confidence: float = 0.60,
    ):
        """
        Initialize spike detector.
        
        Args:
            spike_threshold: Minimum deviation to trigger (0.15 = 15%)
            lookback_periods: Number of periods for moving average
            min_confidence: Minimum confidence to generate signal
        """
        super().__init__("SpikeDetection")
        
        self.spike_threshold = spike_threshold
        self.lookback_periods = lookback_periods
        self.min_confidence = min_confidence
        
        logger.info(
            f"Initialized Spike Detector: "
            f"threshold={spike_threshold:.1%}, "
            f"lookback={lookback_periods}"
        )
    
    def process(
        self,
        current_price: Decimal,
        historical_prices: list[Decimal],
        metadata: Dict[str, Any] = None,
    ) -> Optional[TradingSignal]:
        """
        Detect price spikes and generate mean reversion signal.
        
        Args:
            current_price: Current price
            historical_prices: Recent price history
            metadata: Additional context
            
        Returns:
            TradingSignal if spike detected, None otherwise
        """
        if not self.is_enabled:
            return None
        
        # Need enough history
        if len(historical_prices) < self.lookback_periods:
            return None
        
        # Calculate moving average
        recent_prices = historical_prices[-self.lookback_periods:]
        ma = sum(recent_prices) / len(recent_prices)
        
        # Calculate deviation from MA
        deviation = (current_price - ma) / ma
        deviation_pct = float(abs(deviation))
        
        # Check if spike detected
        if deviation_pct < self.spike_threshold:
            return None  # No significant spike
        
        # Spike detected! Generate counter-trend signal
        logger.info(
            f"Spike detected: {deviation_pct:.2%} from MA "
            f"(${float(current_price):,.2f} vs ${float(ma):,.2f})"
        )
        
        # Determine direction (fade the spike)
        if deviation > 0:
            # Price spiked up → expect reversion down → BEARISH
            direction = SignalDirection.BEARISH
            target_price = ma  # Target mean reversion to MA
        else:
            # Price spiked down → expect reversion up → BULLISH
            direction = SignalDirection.BULLISH
            target_price = ma
        
        # Calculate strength based on spike magnitude
        if deviation_pct >= 0.25:  # >25%
            strength = SignalStrength.VERY_STRONG
        elif deviation_pct >= 0.20:  # >20%
            strength = SignalStrength.STRONG
        elif deviation_pct >= 0.15:  # >15%
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK
        
        # Calculate confidence
        # Higher deviation = higher confidence (to a point)
        confidence = min(0.95, 0.50 + (deviation_pct - self.spike_threshold) * 2)
        
        if confidence < self.min_confidence:
            return None  # Not confident enough
        
        # Calculate stop loss (beyond the spike)
        stop_loss_distance = abs(current_price - ma) * Decimal("1.5")
        
        if direction == SignalDirection.BEARISH:
            stop_loss = current_price + stop_loss_distance
        else:
            stop_loss = current_price - stop_loss_distance
        
        # Create signal
        signal = TradingSignal(
            timestamp=datetime.now(),
            source=self.name,
            signal_type=SignalType.SPIKE_DETECTED,
            direction=direction,
            strength=strength,
            confidence=confidence,
            current_price=current_price,
            target_price=target_price,
            stop_loss=stop_loss,
            metadata={
                "deviation_pct": deviation_pct,
                "moving_average": float(ma),
                "spike_direction": "up" if deviation > 0 else "down",
            }
        )
        
        self._record_signal(signal)
        
        logger.info(
            f"Generated {direction.value} signal: "
            f"confidence={confidence:.2%}, score={signal.score:.1f}"
        )
        
        return signal