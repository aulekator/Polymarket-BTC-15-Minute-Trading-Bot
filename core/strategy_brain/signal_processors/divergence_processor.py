"""
Price Divergence Signal Processor
Detects when Polymarket price diverges from spot exchanges
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


class PriceDivergenceProcessor(BaseSignalProcessor):
    """
    Detects price divergence between Polymarket and spot exchanges.
    
    Logic:
    - Compare Polymarket prediction price vs actual BTC spot price
    - If divergence > threshold, signal arbitrage opportunity
    - Direction: Trade toward convergence
    """
    
    def __init__(
        self,
        divergence_threshold: float = 0.05,  # 5% divergence
        min_confidence: float = 0.65,
    ):
        """
        Initialize divergence processor.
        
        Args:
            divergence_threshold: Minimum divergence to signal (0.05 = 5%)
            min_confidence: Minimum confidence threshold
        """
        super().__init__("PriceDivergence")
        
        self.divergence_threshold = divergence_threshold
        self.min_confidence = min_confidence
        
        logger.info(
            f"Initialized Price Divergence Processor: "
            f"threshold={divergence_threshold:.1%}"
        )
    
    def process(
        self,
        current_price: Decimal,
        historical_prices: list[Decimal],
        metadata: Dict[str, Any] = None,
    ) -> Optional[TradingSignal]:
        """
        Detect price divergence between markets.
        
        Args:
            current_price: Polymarket price
            historical_prices: Not used
            metadata: Must contain 'spot_price' (Coinbase/Binance consensus)
            
        Returns:
            TradingSignal if divergence detected, None otherwise
        """
        if not self.is_enabled:
            return None
        
        if not metadata or 'spot_price' not in metadata:
            return None
        
        spot_price = Decimal(str(metadata['spot_price']))
        
        # Calculate divergence
        divergence = (current_price - spot_price) / spot_price
        divergence_pct = float(abs(divergence))
        
        # Check if divergence is significant
        if divergence_pct < self.divergence_threshold:
            return None  # Not enough divergence
        
        logger.info(
            f"Price divergence detected: {divergence_pct:.2%} "
            f"(Polymarket ${float(current_price):,.2f} vs "
            f"Spot ${float(spot_price):,.2f})"
        )
        
        # Determine direction (trade toward convergence)
        if divergence > 0:
            # Polymarket price too high → expect it to fall → BEARISH
            direction = SignalDirection.BEARISH
            target_price = spot_price
        else:
            # Polymarket price too low → expect it to rise → BULLISH
            direction = SignalDirection.BULLISH
            target_price = spot_price
        
        # Calculate strength based on divergence magnitude
        if divergence_pct >= 0.15:  # >15%
            strength = SignalStrength.VERY_STRONG
        elif divergence_pct >= 0.10:  # >10%
            strength = SignalStrength.STRONG
        elif divergence_pct >= 0.07:  # >7%
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK
        
        # Calculate confidence (higher divergence = higher confidence)
        confidence = min(0.90, 0.60 + divergence_pct)
        
        if confidence < self.min_confidence:
            return None
        
        # Create signal
        signal = TradingSignal(
            timestamp=datetime.now(),
            source=self.name,
            signal_type=SignalType.PRICE_DIVERGENCE,
            direction=direction,
            strength=strength,
            confidence=confidence,
            current_price=current_price,
            target_price=target_price,
            metadata={
                "divergence_pct": divergence_pct,
                "spot_price": float(spot_price),
                "polymarket_price": float(current_price),
            }
        )
        
        self._record_signal(signal)
        
        logger.info(
            f"Generated divergence signal: {direction.value}, "
            f"confidence={confidence:.2%}"
        )
        
        return signal