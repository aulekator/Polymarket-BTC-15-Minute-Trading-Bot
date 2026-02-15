"""
Sentiment Signal Processor
Generates signals based on market sentiment (Fear & Greed Index)
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


class SentimentProcessor(BaseSignalProcessor):
    """
    Generates signals from sentiment data.
    
    Logic:
    - Extreme Fear (0-25) → Contrarian bullish (buy the fear)
    - Fear (25-45) → Mild bullish
    - Neutral (45-55) → No signal
    - Greed (55-75) → Mild bearish
    - Extreme Greed (75-100) → Contrarian bearish (fade the greed)
    """
    
    def __init__(
        self,
        extreme_fear_threshold: float = 25,
        extreme_greed_threshold: float = 75,
        min_confidence: float = 0.50,
    ):
        """
        Initialize sentiment processor.
        
        Args:
            extreme_fear_threshold: Score below this = extreme fear
            extreme_greed_threshold: Score above this = extreme greed
            min_confidence: Minimum confidence to generate signal
        """
        super().__init__("SentimentAnalysis")
        
        self.extreme_fear = extreme_fear_threshold
        self.extreme_greed = extreme_greed_threshold
        self.min_confidence = min_confidence
        
        logger.info(
            f"Initialized Sentiment Processor: "
            f"fear<{extreme_fear_threshold}, greed>{extreme_greed_threshold}"
        )
    
    def process(
        self,
        current_price: Decimal,
        historical_prices: list[Decimal],
        metadata: Dict[str, Any] = None,
    ) -> Optional[TradingSignal]:
        """
        Generate signal from sentiment data.
        
        Args:
            current_price: Current price
            historical_prices: Price history (not used here)
            metadata: Must contain 'sentiment_score' (0-100)
            
        Returns:
            TradingSignal if extreme sentiment detected, None otherwise
        """
        if not self.is_enabled:
            return None
        
        if not metadata or 'sentiment_score' not in metadata:
            return None
        
        sentiment_score = float(metadata['sentiment_score'])
        
        # Determine signal based on sentiment
        if sentiment_score <= self.extreme_fear:
            # Extreme fear → Contrarian buy
            direction = SignalDirection.BULLISH
            signal_type = SignalType.SENTIMENT_SHIFT
            
            # More extreme = stronger signal
            extremeness = (self.extreme_fear - sentiment_score) / self.extreme_fear
            
            if extremeness >= 0.8:  # Very extreme
                strength = SignalStrength.VERY_STRONG
                confidence = 0.85
            elif extremeness >= 0.5:
                strength = SignalStrength.STRONG
                confidence = 0.75
            else:
                strength = SignalStrength.MODERATE
                confidence = 0.65
            
            logger.info(
                f"Extreme fear detected: score={sentiment_score:.1f} "
                f"→ Contrarian BULLISH signal"
            )
            
        elif sentiment_score >= self.extreme_greed:
            # Extreme greed → Contrarian sell
            direction = SignalDirection.BEARISH
            signal_type = SignalType.SENTIMENT_SHIFT
            
            # More extreme = stronger signal
            extremeness = (sentiment_score - self.extreme_greed) / (100 - self.extreme_greed)
            
            if extremeness >= 0.8:
                strength = SignalStrength.VERY_STRONG
                confidence = 0.85
            elif extremeness >= 0.5:
                strength = SignalStrength.STRONG
                confidence = 0.75
            else:
                strength = SignalStrength.MODERATE
                confidence = 0.65
            
            logger.info(
                f"Extreme greed detected: score={sentiment_score:.1f} "
                f"→ Contrarian BEARISH signal"
            )
            
        elif sentiment_score < 45:
            # Moderate fear → Mild bullish
            direction = SignalDirection.BULLISH
            signal_type = SignalType.SENTIMENT_SHIFT
            strength = SignalStrength.WEAK
            confidence = 0.55
            
        elif sentiment_score > 55:
            # Moderate greed → Mild bearish
            direction = SignalDirection.BEARISH
            signal_type = SignalType.SENTIMENT_SHIFT
            strength = SignalStrength.WEAK
            confidence = 0.55
            
        else:
            # Neutral sentiment → No signal
            return None
        
        # Check minimum confidence
        if confidence < self.min_confidence:
            return None
        
        # Create signal
        signal = TradingSignal(
            timestamp=datetime.now(),
            source=self.name,
            signal_type=signal_type,
            direction=direction,
            strength=strength,
            confidence=confidence,
            current_price=current_price,
            metadata={
                "sentiment_score": sentiment_score,
                "sentiment_classification": metadata.get('sentiment_classification', 'unknown'),
            }
        )
        
        self._record_signal(signal)
        
        logger.debug(
            f"Generated sentiment signal: {direction.value}, "
            f"score={signal.score:.1f}"
        )
        
        return signal