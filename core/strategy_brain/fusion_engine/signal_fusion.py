"""
Signal Fusion Engine
Combines multiple signals with weighted voting
"""
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from loguru import logger

import os 
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.strategy_brain.signal_processors.base_processor import (
    TradingSignal,
    SignalDirection,
    SignalStrength,
)


@dataclass
class FusedSignal:
    timestamp: datetime
    direction: SignalDirection
    confidence: float
    score: float
    
    signals: List[TradingSignal]
    weights: Dict[str, float]
    metadata: Dict[str, Any]
    
    @property
    def num_signals(self) -> int:
        return len(self.signals)
    
    @property
    def is_strong(self) -> bool:
        return self.score >= 70.0
    
    @property
    def is_actionable(self) -> bool:
        return self.score >= 60.0 and self.confidence >= 0.6


class SignalFusionEngine:
    def __init__(self):
        self.weights = {
            "SpikeDetection":    0.40,
            "PriceDivergence":   0.30,
            "SentimentAnalysis": 0.20,
            "default":           0.10,
        }
        
        self._signal_history: List[FusedSignal] = []
        self._max_history = 100
        self._fusions_performed = 0
        
        logger.info("Initialized Signal Fusion Engine")
        logger.info(f"Weights: {self.weights}")
    
    def set_weight(self, processor_name: str, weight: float) -> None:
        if not 0.0 <= weight <= 1.0:
            raise ValueError("Weight must be between 0.0 and 1.0")
        self.weights[processor_name] = weight
        logger.info(f"Set weight for {processor_name}: {weight:.2f}")
    
    def fuse_signals(
        self,
        signals: List[TradingSignal],
        min_signals: int = 1,
        min_score: float = 50.0,
    ) -> Optional[FusedSignal]:
        if not signals:
            logger.debug("No signals to fuse")
            return None
        
        if len(signals) < min_signals:
            logger.debug(f"Not enough signals: {len(signals)} < {min_signals}")
            return None
        
        current_time = datetime.now()
        recent_signals = [
            s for s in signals
            if (current_time - s.timestamp) < timedelta(minutes=5)
        ]
        
        if len(recent_signals) < min_signals:
            logger.debug(f"Not enough recent signals: {len(recent_signals)}")
            return None
        
        bullish_contrib = 0.0
        bearish_contrib = 0.0
        
        for signal in recent_signals:
            weight = self.weights.get(signal.source, self.weights["default"])
            
            strength_val = signal.strength.value if signal.strength else 2
            strength_factor = strength_val / 4.0
            
            conf = min(1.0, max(0.0, signal.confidence))
            
            contribution = weight * conf * strength_factor
            
            logger.debug(
                f"Signal {signal.source}: dir={signal.direction}, "
                f"strength={signal.strength.name if signal.strength else 'MISSING'}, "
                f"conf={conf:.3f}, weight={weight:.2f}, str_factor={strength_factor:.3f}, "
                f"contrib={contribution:.6f}"
            )
            
            # FIXED: string-based direction check (your direction is likely str, not enum)
            direction_str = str(signal.direction).upper()
            if "BULLISH" in direction_str:
                bullish_contrib += contribution
                logger.debug(f"  → ADDED to BULLISH → current: {bullish_contrib:.6f}")
            elif "BEARISH" in direction_str:
                bearish_contrib += contribution
                logger.debug(f"  → ADDED to BEARISH → current: {bearish_contrib:.6f}")
            else:
                logger.warning(f"Ignored unknown direction: {signal.direction!r}")
        
        total_contrib = bullish_contrib + bearish_contrib
        logger.debug(f"Final: bullish={bullish_contrib:.6f} | bearish={bearish_contrib:.6f} | total={total_contrib:.6f}")
        
        if total_contrib < 0.0001:
            logger.warning(f"Extremely weak total contribution: {total_contrib:.8f} → fusion skipped")
            return None
        
        if bullish_contrib >= bearish_contrib:
            direction = SignalDirection.BULLISH if "BULLISH" in str(SignalDirection.BULLISH) else "BULLISH"
            dominant = bullish_contrib
        else:
            direction = SignalDirection.BEARISH if "BEARISH" in str(SignalDirection.BEARISH) else "BEARISH"
            dominant = bearish_contrib
        
        consensus_score = (dominant / total_contrib) * 100 if total_contrib > 0 else 0.0
        
        avg_conf = sum(s.confidence for s in recent_signals) / len(recent_signals) if recent_signals else 0.0
        
        if consensus_score < min_score:
            logger.debug(f"Consensus score too low: {consensus_score:.1f} < {min_score}")
            return None
        
        fused = FusedSignal(
            timestamp=current_time,
            direction=direction,
            confidence=avg_conf,
            score=consensus_score,
            signals=recent_signals,
            weights=self.weights.copy(),
            metadata={
                "bullish_contrib": round(bullish_contrib, 4),
                "bearish_contrib": round(bearish_contrib, 4),
                "total_contrib": round(total_contrib, 4),
                "num_bullish": sum(1 for s in recent_signals if "BULLISH" in str(s.direction).upper()),
                "num_bearish": sum(1 for s in recent_signals if "BEARISH" in str(s.direction).upper()),
            }
        )
        
        self._fusions_performed += 1
        self._signal_history.append(fused)
        if len(self._signal_history) > self._max_history:
            self._signal_history.pop(0)
        
        logger.info(
            f"Fused {len(recent_signals)} signals → {direction} "
            f"(score={consensus_score:.1f}, conf={avg_conf:.1%})"
        )
        
        return fused
    
    def get_recent_fusions(self, limit: int = 10) -> List[FusedSignal]:
        return self._signal_history[-limit:]
    
    def get_statistics(self) -> Dict[str, Any]:
        if not self._signal_history:
            return {
                "total_fusions": self._fusions_performed,
                "recent_fusions": 0,
                "avg_score": 0.0,
                "avg_confidence": 0.0,
            }
        
        recent = self._signal_history[-20:]
        return {
            "total_fusions": self._fusions_performed,
            "recent_fusions": len(recent),
            "avg_score": sum(f.score for f in recent) / len(recent) if recent else 0.0,
            "avg_confidence": sum(f.confidence for f in recent) / len(recent) if recent else 0.0,
            "weights": self.weights.copy(),
        }


_fusion_engine_instance = None

def get_fusion_engine() -> SignalFusionEngine:
    global _fusion_engine_instance
    if _fusion_engine_instance is None:
        _fusion_engine_instance = SignalFusionEngine()
    return _fusion_engine_instance