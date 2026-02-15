"""
Performance Tracker
Tracks and analyzes trading performance metrics
"""
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from collections import deque
from loguru import logger


@dataclass
class Trade:
    """Individual trade record."""
    trade_id: str
    timestamp: datetime
    direction: str  # "long" or "short"
    entry_price: Decimal
    exit_price: Decimal
    size: Decimal
    pnl: Decimal
    pnl_pct: float
    duration_seconds: float
    signal_score: float
    signal_confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceMetrics:
    """Performance metrics snapshot."""
    timestamp: datetime
    
    # P&L metrics
    total_pnl: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    
    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    
    # Return metrics
    roi: float  # Return on investment
    sharpe_ratio: float
    max_drawdown: float
    
    # Position metrics
    open_positions: int
    avg_position_size: Decimal
    avg_hold_time: float  # seconds
    
    # Risk metrics
    total_exposure: Decimal
    risk_utilization: float  # % of max risk used
    
    # Signal performance
    avg_signal_score: float
    avg_signal_confidence: float


class PerformanceTracker:
    """
    Tracks and analyzes trading performance.
    
    Features:
    - Trade history
    - Performance metrics
    - Risk analytics
    - Signal effectiveness
    """
    
    def __init__(
        self,
        initial_capital: Decimal = Decimal("1000.0"),
    ):
        """
        Initialize performance tracker.
        
        Args:
            initial_capital: Starting capital
        """
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        
        # Trade history
        self._trades: List[Trade] = []
        self._max_trades_history = 1000
        
        # Metrics history (for Grafana)
        self._metrics_history: deque = deque(maxlen=10000)
        
        # Performance cache
        self._last_metrics: Optional[PerformanceMetrics] = None
        self._metrics_dirty = True
        
        # Peak tracking for drawdown
        self._peak_capital = initial_capital
        
        logger.info(f"Initialized Performance Tracker (capital=${initial_capital})")
    
    def record_trade(
        self,
        trade_id: str,
        direction: str,
        entry_price: Decimal,
        exit_price: Decimal,
        size: Decimal,
        entry_time: datetime,
        exit_time: datetime,
        signal_score: float = 0.0,
        signal_confidence: float = 0.0,
        metadata: Dict[str, Any] = None,
    ) -> Trade:
        """
        Record a completed trade.
        
        Args:
            trade_id: Unique trade ID
            direction: "long" or "short"
            entry_price: Entry price
            exit_price: Exit price
            size: Position size
            entry_time: Entry timestamp
            exit_time: Exit timestamp
            signal_score: Signal score that triggered trade
            signal_confidence: Signal confidence
            metadata: Additional trade metadata
            
        Returns:
            Trade record
        """
        # Calculate P&L
        if direction == "long":
            pnl_pct = (exit_price - entry_price) / entry_price
        else:  # short
            pnl_pct = (entry_price - exit_price) / entry_price
        
        pnl = size * pnl_pct
        
        # Calculate duration
        duration = (exit_time - entry_time).total_seconds()
        
        # Create trade record
        trade = Trade(
            trade_id=trade_id,
            timestamp=exit_time,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            size=size,
            pnl=pnl,
            pnl_pct=float(pnl_pct),
            duration_seconds=duration,
            signal_score=signal_score,
            signal_confidence=signal_confidence,
            metadata=metadata or {},
        )
        
        # Store trade
        self._trades.append(trade)
        
        # Limit history size
        if len(self._trades) > self._max_trades_history:
            self._trades.pop(0)
        
        # Update capital
        self.current_capital += pnl
        
        # Update peak for drawdown tracking
        if self.current_capital > self._peak_capital:
            self._peak_capital = self.current_capital
        
        # Mark metrics as dirty
        self._metrics_dirty = True
        
        logger.info(
            f"Recorded trade: {trade_id} "
            f"{direction.upper()} P&L=${pnl:+.2f} ({pnl_pct:+.2%})"
        )
        
        return trade
    
    def calculate_metrics(self, force: bool = False) -> PerformanceMetrics:
        """
        Calculate current performance metrics.
        
        Args:
            force: Force recalculation even if cache valid
            
        Returns:
            Current performance metrics
        """
        # Return cached if available and not dirty
        if not force and not self._metrics_dirty and self._last_metrics:
            return self._last_metrics
        
        # Calculate metrics
        total_pnl = self.current_capital - self.initial_capital
        
        # Trade statistics
        total_trades = len(self._trades)
        winning_trades = len([t for t in self._trades if t.pnl > 0])
        losing_trades = len([t for t in self._trades if t.pnl < 0])
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        
        # Return metrics
        roi = float((self.current_capital - self.initial_capital) / self.initial_capital)
        
        # Sharpe ratio (simplified - uses daily returns)
        sharpe = self._calculate_sharpe_ratio()
        
        # Max drawdown
        max_dd = float((self._peak_capital - self.current_capital) / self._peak_capital) if self._peak_capital > 0 else 0.0
        
        # Position metrics
        if total_trades > 0:
            avg_size = sum(t.size for t in self._trades) / total_trades
            avg_hold = sum(t.duration_seconds for t in self._trades) / total_trades
            avg_score = sum(t.signal_score for t in self._trades) / total_trades
            avg_conf = sum(t.signal_confidence for t in self._trades) / total_trades
        else:
            avg_size = Decimal("0")
            avg_hold = 0.0
            avg_score = 0.0
            avg_conf = 0.0
        
        # Create metrics
        metrics = PerformanceMetrics(
            timestamp=datetime.now(),
            total_pnl=total_pnl,
            realized_pnl=total_pnl,  # All P&L is realized from closed trades
            unrealized_pnl=Decimal("0"),  # No open positions tracked here
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            roi=roi,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            open_positions=0,
            avg_position_size=avg_size,
            avg_hold_time=avg_hold,
            total_exposure=Decimal("0"),
            risk_utilization=0.0,
            avg_signal_score=avg_score,
            avg_signal_confidence=avg_conf,
        )
        
        # Cache metrics
        self._last_metrics = metrics
        self._metrics_dirty = False
        
        # Add to history for Grafana
        self._metrics_history.append(metrics)
        
        return metrics
    
    def _calculate_sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """
        Calculate Sharpe ratio.
        
        Args:
            risk_free_rate: Annual risk-free rate (default 2%)
            
        Returns:
            Sharpe ratio
        """
        if len(self._trades) < 2:
            return 0.0
        
        # Get daily returns
        returns = [float(t.pnl / t.size) for t in self._trades if t.size > 0]
        
        if not returns:
            return 0.0
        
        # Calculate mean and std
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = variance ** 0.5
        
        if std_return == 0:
            return 0.0
        
        # Sharpe = (mean return - risk free) / std
        # Annualize assuming 252 trading days
        sharpe = (mean_return - risk_free_rate / 252) / std_return * (252 ** 0.5)
        
        return sharpe
    
    def get_trade_history(
        self,
        limit: int = 100,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[Trade]:
        """
        Get trade history.
        
        Args:
            limit: Maximum trades to return
            start_date: Filter trades after this date
            end_date: Filter trades before this date
            
        Returns:
            List of trades
        """
        trades = self._trades
        
        # Apply date filters
        if start_date:
            trades = [t for t in trades if t.timestamp >= start_date]
        
        if end_date:
            trades = [t for t in trades if t.timestamp <= end_date]
        
        # Return most recent trades
        return trades[-limit:]
    
    def get_equity_curve(self) -> List[Dict[str, Any]]:
        """
        Get equity curve over time.
        
        Returns:
            List of {timestamp, equity} points
        """
        curve = [
            {
                "timestamp": self._trades[0].timestamp if self._trades else datetime.now(),
                "equity": float(self.initial_capital),
            }
        ]
        
        running_capital = self.initial_capital
        
        for trade in self._trades:
            running_capital += trade.pnl
            curve.append({
                "timestamp": trade.timestamp,
                "equity": float(running_capital),
            })
        
        return curve
    
    def get_daily_pnl(self, days: int = 30) -> List[Dict[str, Any]]:
        """
        Get daily P&L summary.
        
        Args:
            days: Number of days to include
            
        Returns:
            List of daily P&L
        """
        cutoff = datetime.now() - timedelta(days=days)
        recent_trades = [t for t in self._trades if t.timestamp >= cutoff]
        
        # Group by day
        daily_pnl: Dict[str, Decimal] = {}
        
        for trade in recent_trades:
            day_key = trade.timestamp.strftime("%Y-%m-%d")
            
            if day_key not in daily_pnl:
                daily_pnl[day_key] = Decimal("0")
            
            daily_pnl[day_key] += trade.pnl
        
        # Convert to list
        return [
            {
                "date": day,
                "pnl": float(pnl),
            }
            for day, pnl in sorted(daily_pnl.items())
        ]
    
    def get_win_loss_distribution(self) -> Dict[str, Any]:
        """
        Get win/loss distribution statistics.
        
        Returns:
            Distribution statistics
        """
        wins = [t.pnl for t in self._trades if t.pnl > 0]
        losses = [t.pnl for t in self._trades if t.pnl < 0]
        
        return {
            "total_trades": len(self._trades),
            "wins": {
                "count": len(wins),
                "total": float(sum(wins)),
                "avg": float(sum(wins) / len(wins)) if wins else 0.0,
                "max": float(max(wins)) if wins else 0.0,
            },
            "losses": {
                "count": len(losses),
                "total": float(sum(losses)),
                "avg": float(sum(losses) / len(losses)) if losses else 0.0,
                "max": float(min(losses)) if losses else 0.0,
            },
            "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 0.0,
        }
    
    def export_for_grafana(self) -> Dict[str, Any]:
        """
        Export data in Grafana-friendly format.
        
        Returns:
            Dict with time-series data
        """
        metrics = self.calculate_metrics()
        
        return {
            "timestamp": datetime.now().isoformat(),
            "metrics": {
                "total_pnl": float(metrics.total_pnl),
                "roi": metrics.roi * 100,  # As percentage
                "win_rate": metrics.win_rate * 100,
                "sharpe_ratio": metrics.sharpe_ratio,
                "max_drawdown": metrics.max_drawdown * 100,
                "total_trades": metrics.total_trades,
                "current_capital": float(self.current_capital),
            },
            "equity_curve": self.get_equity_curve(),
            "daily_pnl": self.get_daily_pnl(30),
        }


# Singleton instance
_performance_tracker_instance = None

def get_performance_tracker() -> PerformanceTracker:
    """Get singleton performance tracker."""
    global _performance_tracker_instance
    if _performance_tracker_instance is None:
        _performance_tracker_instance = PerformanceTracker()
    return _performance_tracker_instance