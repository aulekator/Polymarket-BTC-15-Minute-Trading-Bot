"""
Learning Engine
Learns from trading performance to optimize strategy weights
"""
import asyncio
import json
from decimal import Decimal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from loguru import logger

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from monitoring.performance_tracker import get_performance_tracker, Trade
from core.strategy_brain.fusion_engine.signal_fusion import get_fusion_engine


@dataclass
class SignalPerformance:
    """Performance metrics for a signal source."""
    source_name: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_pnl: Decimal
    total_pnl: Decimal
    avg_confidence: float
    avg_score: float
    last_updated: datetime


class LearningEngine:
    """
    Learning engine that optimizes strategy based on performance.
    
    Features:
    - Analyzes signal source performance
    - Adjusts fusion weights
    - Identifies winning patterns
    - Improves over time
    """
    
    def __init__(
        self,
        learning_rate: float = 0.1,
        min_trades_for_learning: int = 10,
    ):
        """
        Initialize learning engine.
        
        Args:
            learning_rate: How quickly to adjust weights (0-1)
            min_trades_for_learning: Minimum trades before adjusting
        """
        self.learning_rate = learning_rate
        self.min_trades = min_trades_for_learning
        
        # Components
        self.performance = get_performance_tracker()
        self.fusion = get_fusion_engine()
        
        # Signal performance tracking
        self._signal_performance: Dict[str, SignalPerformance] = {}
        
        # Learning history
        self._weight_adjustments: List[Dict[str, Any]] = []
        
        # Persistence
        self._state_file = Path("learning_state.json")
        
        # Auto-load saved state if available
        self._load_state()
        
        logger.info(
            f"Initialized Learning Engine "
            f"(learning_rate={learning_rate}, min_trades={min_trades_for_learning})"
        )
    
    def analyze_signal_performance(
        self,
        lookback_days: int = 7,
    ) -> Dict[str, SignalPerformance]:
        """
        Analyze performance of each signal source.
        
        Args:
            lookback_days: Number of days to analyze
            
        Returns:
            Performance metrics per signal source
        """
        cutoff = datetime.now() - timedelta(days=lookback_days)
        trades = self.performance.get_trade_history(
            limit=1000,
            start_date=cutoff,
        )
        
        # Group trades by signal source
        source_trades: Dict[str, List[Trade]] = {}
        
        for trade in trades:
            # Extract signal source from metadata
            # This assumes trades store which signal triggered them
            sources = trade.metadata.get("signal_sources", [])
            
            for source in sources:
                if source not in source_trades:
                    source_trades[source] = []
                
                source_trades[source].append(trade)
        
        # Calculate performance per source
        performances = {}
        
        for source, source_trade_list in source_trades.items():
            wins = [t for t in source_trade_list if t.pnl > 0]
            losses = [t for t in source_trade_list if t.pnl < 0]
            
            total = len(source_trade_list)
            win_count = len(wins)
            loss_count = len(losses)
            
            win_rate = win_count / total if total > 0 else 0.0
            
            avg_pnl = sum(t.pnl for t in source_trade_list) / total if total > 0 else Decimal("0")
            total_pnl = sum(t.pnl for t in source_trade_list)
            
            avg_conf = sum(t.signal_confidence for t in source_trade_list) / total if total > 0 else 0.0
            avg_score = sum(t.signal_score for t in source_trade_list) / total if total > 0 else 0.0
            
            perf = SignalPerformance(
                source_name=source,
                total_trades=total,
                winning_trades=win_count,
                losing_trades=loss_count,
                win_rate=win_rate,
                avg_pnl=avg_pnl,
                total_pnl=total_pnl,
                avg_confidence=avg_conf,
                avg_score=avg_score,
                last_updated=datetime.now(),
            )
            
            performances[source] = perf
            self._signal_performance[source] = perf
        
        logger.info(f"Analyzed performance for {len(performances)} signal sources")
        
        return performances
    
    def calculate_optimal_weights(
        self,
        performances: Dict[str, SignalPerformance],
    ) -> Dict[str, float]:
        """
        Calculate optimal weights based on performance.
        
        Args:
            performances: Signal performance metrics
            
        Returns:
            Optimized weights per signal source
        """
        # Simple approach: Weight by win rate and total P&L
        weights = {}
        
        for source, perf in performances.items():
            # Skip if not enough trades
            if perf.total_trades < self.min_trades:
                weights[source] = self.fusion.weights.get(source, 0.1)
                continue
            
            # Calculate performance score
            # Combines win rate and profitability
            win_rate_score = perf.win_rate
            pnl_score = min(1.0, max(0.0, float(perf.total_pnl / Decimal("100"))))
            
            # Weighted combination
            performance_score = (win_rate_score * 0.6) + (pnl_score * 0.4)
            
            # Apply learning rate (gradual adjustment)
            current_weight = self.fusion.weights.get(source, 0.1)
            target_weight = performance_score
            
            new_weight = current_weight + (target_weight - current_weight) * self.learning_rate
            
            # Clamp to reasonable range
            new_weight = max(0.05, min(0.50, new_weight))
            
            weights[source] = new_weight
        
        # Normalize weights to sum to 1.0
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}
        
        return weights
    
    async def optimize_weights(self) -> Dict[str, float]:
        """
        Optimize signal fusion weights based on performance.
        
        Returns:
            New weights
        """
        logger.info("=" * 60)
        logger.info("OPTIMIZING SIGNAL WEIGHTS")
        logger.info("=" * 60)
        
        # Analyze performance
        performances = self.analyze_signal_performance(lookback_days=7)
        
        if not performances:
            logger.warning("No performance data available for optimization")
            return self.fusion.weights.copy()
        
        # Calculate optimal weights
        new_weights = self.calculate_optimal_weights(performances)
        
        # Log changes
        logger.info("Weight adjustments:")
        for source, new_weight in new_weights.items():
            old_weight = self.fusion.weights.get(source, 0.0)
            change = new_weight - old_weight
            
            logger.info(
                f"  {source}: {old_weight:.3f} → {new_weight:.3f} "
                f"({change:+.3f})"
            )
        
        # Apply new weights
        for source, weight in new_weights.items():
            self.fusion.set_weight(source, weight)
        
        # Record adjustment
        self._weight_adjustments.append({
            "timestamp": datetime.now(),
            "old_weights": self.fusion.weights.copy(),
            "new_weights": new_weights.copy(),
            "performances": {
                source: {
                    "win_rate": perf.win_rate,
                    "total_pnl": float(perf.total_pnl),
                    "trades": perf.total_trades,
                }
                for source, perf in performances.items()
            },
        })
        
        logger.info("✓ Weights optimized successfully")
        
        # Auto-save after optimization
        self._save_state()
        
        return new_weights
    
    def _save_state(self) -> None:
        """Persist weights and learning history to disk."""
        try:
            state = {
                "saved_at": datetime.now().isoformat(),
                "weights": dict(self.fusion.weights),
                "adjustments_count": len(self._weight_adjustments),
                "last_adjustment": (
                    {
                        k: v for k, v in self._weight_adjustments[-1].items()
                        if k != "timestamp"  # datetime not JSON serializable
                    }
                    if self._weight_adjustments else None
                ),
            }
            self._state_file.write_text(json.dumps(state, indent=2))
            logger.info(f"Learning state saved to {self._state_file}")
        except Exception as e:
            logger.warning(f"Failed to save learning state: {e}")
    
    def _load_state(self) -> None:
        """Restore weights from disk if state file exists."""
        if not self._state_file.exists():
            return
        try:
            state = json.loads(self._state_file.read_text())
            saved_weights = state.get("weights", {})
            if saved_weights:
                for source, weight in saved_weights.items():
                    self.fusion.set_weight(source, weight)
                logger.info(
                    f"Restored learning state from {self._state_file} "
                    f"(saved at {state.get('saved_at', 'unknown')}, "
                    f"{state.get('adjustments_count', 0)} prior adjustments)"
                )
        except Exception as e:
            logger.warning(f"Failed to load learning state: {e}")
    
    def get_signal_rankings(self) -> List[Dict[str, Any]]:
        """
        Get signals ranked by performance.
        
        Returns:
            List of signals sorted by performance
        """
        rankings = []
        
        for source, perf in self._signal_performance.items():
            rankings.append({
                "source": source,
                "win_rate": perf.win_rate,
                "total_pnl": float(perf.total_pnl),
                "avg_pnl": float(perf.avg_pnl),
                "total_trades": perf.total_trades,
                "current_weight": self.fusion.weights.get(source, 0.0),
            })
        
        # Sort by total P&L
        rankings.sort(key=lambda x: x["total_pnl"], reverse=True)
        
        return rankings
    
    def get_learning_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get history of weight adjustments.
        
        Args:
            limit: Max adjustments to return
            
        Returns:
            List of weight adjustments
        """
        return self._weight_adjustments[-limit:]
    
    def export_insights(self) -> Dict[str, Any]:
        """
        Export learning insights.
        
        Returns:
            Insights dict
        """
        return {
            "timestamp": datetime.now().isoformat(),
            "signal_performance": {
                source: {
                    "win_rate": perf.win_rate,
                    "total_pnl": float(perf.total_pnl),
                    "total_trades": perf.total_trades,
                    "current_weight": self.fusion.weights.get(source, 0.0),
                }
                for source, perf in self._signal_performance.items()
            },
            "signal_rankings": self.get_signal_rankings(),
            "recent_adjustments": self.get_learning_history(5),
        }


# Singleton instance
_learning_engine_instance = None

def get_learning_engine() -> LearningEngine:
    """Get singleton learning engine."""
    global _learning_engine_instance
    if _learning_engine_instance is None:
        _learning_engine_instance = LearningEngine()
    return _learning_engine_instance