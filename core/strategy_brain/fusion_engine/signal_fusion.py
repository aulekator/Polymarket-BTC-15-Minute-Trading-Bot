"""
Signal Fusion Engine
Combines multiple signals with weighted voting.

Optimized: direct enum comparison, deque history, no redundant copies.
"""
from collections import deque
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
            "SpikeDetection":       0.15,
            "PriceDivergence":      0.10,
            "SentimentAnalysis":    0.10,
            "TickVelocity":         0.25,   # Most direct: Polymarket orderflow
            "OrderBookImbalance":   0.25,   # Real-time CLOB depth
            "DeribitPCR":           0.15,   # Institutional options sentiment
            "default":              0.05,
        }

        # Use deque for O(1) eviction instead of list.pop(0)
        self._signal_history: deque = deque(maxlen=100)
        self._fusions_performed = 0
        # Snapshot of weights at last change — avoids .copy() on every fusion
        self._weights_snapshot: Optional[Dict[str, float]] = None

        logger.info("Initialized Signal Fusion Engine")
        logger.info(f"Weights: {self.weights}")

    def set_weight(self, processor_name: str, weight: float) -> None:
        if not 0.0 <= weight <= 1.0:
            raise ValueError("Weight must be between 0.0 and 1.0")
        self.weights[processor_name] = weight
        self._weights_snapshot = None  # Invalidate snapshot
        logger.info(f"Set weight for {processor_name}: {weight:.2f}")

    def _get_weights_snapshot(self) -> Dict[str, float]:
        """Return a cached copy of weights (only recopied when weights change)."""
        if self._weights_snapshot is None:
            self._weights_snapshot = self.weights.copy()
        return self._weights_snapshot

    def fuse_signals(
        self,
        signals: List[TradingSignal],
        min_signals: int = 1,
        min_score: float = 50.0,
    ) -> Optional[FusedSignal]:
        if not signals:
            return None

        if len(signals) < min_signals:
            return None

        current_time = datetime.now()
        cutoff = current_time - timedelta(minutes=5)
        recent_signals = [s for s in signals if s.timestamp > cutoff]

        if len(recent_signals) < min_signals:
            return None

        bullish_contrib = 0.0
        bearish_contrib = 0.0
        total_confidence = 0.0

        for signal in recent_signals:
            weight = self.weights.get(signal.source, self.weights["default"])

            strength_val = signal.strength.value if signal.strength else 2
            strength_factor = strength_val * 0.25  # /4.0

            conf = signal.confidence
            if conf < 0.0:
                conf = 0.0
            elif conf > 1.0:
                conf = 1.0

            contribution = weight * conf * strength_factor
            total_confidence += conf

            # Direct enum comparison — no str() casts
            if signal.direction is SignalDirection.BULLISH:
                bullish_contrib += contribution
            elif signal.direction is SignalDirection.BEARISH:
                bearish_contrib += contribution

        total_contrib = bullish_contrib + bearish_contrib

        if total_contrib < 0.0001:
            return None

        if bullish_contrib >= bearish_contrib:
            direction = SignalDirection.BULLISH
            dominant = bullish_contrib
        else:
            direction = SignalDirection.BEARISH
            dominant = bearish_contrib

        consensus_score = (dominant / total_contrib) * 100

        n = len(recent_signals)
        avg_conf = total_confidence / n if n else 0.0

        if consensus_score < min_score:
            return None

        # Count directions via enum identity (no str() needed)
        num_bullish = sum(1 for s in recent_signals if s.direction is SignalDirection.BULLISH)

        fused = FusedSignal(
            timestamp=current_time,
            direction=direction,
            confidence=avg_conf,
            score=consensus_score,
            signals=recent_signals,
            weights=self._get_weights_snapshot(),
            metadata={
                "bullish_contrib": round(bullish_contrib, 4),
                "bearish_contrib": round(bearish_contrib, 4),
                "total_contrib": round(total_contrib, 4),
                "num_bullish": num_bullish,
                "num_bearish": n - num_bullish,
            }
        )

        self._fusions_performed += 1
        self._signal_history.append(fused)  # deque auto-evicts

        logger.info(
            f"Fused {n} signals → {direction.value} "
            f"(score={consensus_score:.1f}, conf={avg_conf:.1%})"
        )

        return fused

    def get_recent_fusions(self, limit: int = 10) -> List[FusedSignal]:
        # deque doesn't support [-limit:] slicing, convert tail
        if limit >= len(self._signal_history):
            return list(self._signal_history)
        return list(self._signal_history)[-limit:]

    def get_statistics(self) -> Dict[str, Any]:
        if not self._signal_history:
            return {
                "total_fusions": self._fusions_performed,
                "recent_fusions": 0,
                "avg_score": 0.0,
                "avg_confidence": 0.0,
            }

        recent = list(self._signal_history)[-20:]
        n = len(recent)
        return {
            "total_fusions": self._fusions_performed,
            "recent_fusions": n,
            "avg_score": sum(f.score for f in recent) / n,
            "avg_confidence": sum(f.confidence for f in recent) / n,
            "weights": self._get_weights_snapshot(),
        }


_fusion_engine_instance = None

def get_fusion_engine() -> SignalFusionEngine:
    global _fusion_engine_instance
    if _fusion_engine_instance is None:
        _fusion_engine_instance = SignalFusionEngine()
    return _fusion_engine_instance