"""
Base Signal Processor
Abstract interface for all signal processors
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any
from enum import Enum


class SignalType(Enum):
    """Types of trading signals."""
    SPIKE_DETECTED = "spike_detected"
    MEAN_REVERSION = "mean_reversion"
    MOMENTUM = "momentum"
    SENTIMENT_SHIFT = "sentiment_shift"
    VOLUME_SURGE = "volume_surge"
    PRICE_DIVERGENCE = "price_divergence"
    ANOMALY = "anomaly"


class SignalStrength(Enum):
    """Signal strength levels."""
    WEAK = 1
    MODERATE = 2
    STRONG = 3
    VERY_STRONG = 4


class SignalDirection(Enum):
    """Signal direction."""
    BULLISH = "bullish"  # Expect price to go up
    BEARISH = "bearish"  # Expect price to go down
    NEUTRAL = "neutral"


@dataclass
class TradingSignal:
    """
    Trading signal from a processor.
    
    Represents a trading opportunity detected by analysis.
    """
    timestamp: datetime
    source: str  # Which processor generated this
    signal_type: SignalType
    direction: SignalDirection
    strength: SignalStrength
    confidence: float  # 0.0 - 1.0
    
    # Price context
    current_price: Decimal
    target_price: Optional[Decimal] = None
    stop_loss: Optional[Decimal] = None
    
    # Additional data
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    @property
    def score(self) -> float:
        """
        Calculate signal score (0-100).
        
        Combines strength and confidence.
        """
        strength_weight = self.strength.value / 4.0  # Normalize to 0-1
        return (strength_weight * 0.5 + self.confidence * 0.5) * 100


class BaseSignalProcessor(ABC):
    """
    Base class for all signal processors.
    
    Signal processors analyze market data and generate trading signals.
    """
    
    def __init__(self, name: str):
        """
        Initialize signal processor.
        
        Args:
            name: Processor name
        """
        self.name = name
        self._enabled = True
        
        # Statistics
        self._signals_generated = 0
        self._last_signal: Optional[TradingSignal] = None
    
    @abstractmethod
    def process(
        self,
        current_price: Decimal,
        historical_prices: list[Decimal],
        metadata: Dict[str, Any] = None,
    ) -> Optional[TradingSignal]:
        """
        Process market data and generate signal if conditions met.
        
        Args:
            current_price: Current market price
            historical_prices: List of recent prices
            metadata: Additional context (volume, sentiment, etc.)
            
        Returns:
            TradingSignal if opportunity detected, None otherwise
        """
        pass
    
    def enable(self) -> None:
        """Enable this processor."""
        self._enabled = True
    
    def disable(self) -> None:
        """Disable this processor."""
        self._enabled = False
    
    @property
    def is_enabled(self) -> bool:
        """Check if processor is enabled."""
        return self._enabled
    
    @property
    def signals_generated(self) -> int:
        """Get total signals generated."""
        return self._signals_generated
    
    def _record_signal(self, signal: TradingSignal) -> None:
        """Record that a signal was generated."""
        self._signals_generated += 1
        self._last_signal = signal
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processor statistics."""
        return {
            "name": self.name,
            "enabled": self._enabled,
            "signals_generated": self._signals_generated,
            "last_signal": {
                "timestamp": self._last_signal.timestamp.isoformat(),
                "type": self._last_signal.signal_type.value,
                "direction": self._last_signal.direction.value,
                "score": self._last_signal.score,
            } if self._last_signal else None
        }