"""
Data Validator
Validates incoming market data for quality and anomalies
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from loguru import logger


@dataclass
class ValidationRule:
    """Data validation rule."""
    name: str
    min_value: Optional[Decimal] = None
    max_value: Optional[Decimal] = None
    max_change_percent: Optional[float] = None
    required: bool = True


@dataclass
class ValidationResult:
    """Result of data validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    metadata: Dict[str, Any]


class DataValidator:
    """
    Validates market data for:
    - Price sanity checks
    - Anomaly detection
    - Data completeness
    - Timestamp validation
    """
    
    def __init__(self):
        """Initialize data validator."""
        # Price history for anomaly detection
        self._price_history: Dict[str, List[Decimal]] = {}
        self._max_history_size = 100
        
        # Validation rules
        self.btc_rules = {
            "price": ValidationRule(
                name="BTC Price",
                min_value=Decimal("1000"),  # BTC never below $1k (sanity check)
                max_value=Decimal("1000000"),  # BTC never above $1M (yet!)
                max_change_percent=20.0,  # Max 20% change between updates
            ),
            "volume": ValidationRule(
                name="Volume",
                min_value=Decimal("0"),
                required=False,
            ),
        }
        
        logger.info("Initialized Data Validator")
    
    def validate_market_data(
        self,
        source: str,
        price: Decimal,
        timestamp: datetime,
        volume: Optional[Decimal] = None,
        bid: Optional[Decimal] = None,
        ask: Optional[Decimal] = None,
    ) -> ValidationResult:
        """
        Validate market data.
        
        Args:
            source: Data source name
            price: Current price
            timestamp: Data timestamp
            volume: Trading volume (optional)
            bid: Bid price (optional)
            ask: Ask price (optional)
            
        Returns:
            ValidationResult with is_valid flag and error messages
        """
        errors = []
        warnings = []
        metadata = {}
        
        # 1. Validate price range
        price_rule = self.btc_rules["price"]
        
        if price < price_rule.min_value:
            errors.append(
                f"Price ${price:,.2f} below minimum ${price_rule.min_value:,.2f}"
            )
        
        if price > price_rule.max_value:
            errors.append(
                f"Price ${price:,.2f} above maximum ${price_rule.max_value:,.2f}"
            )
        
        # 2. Validate timestamp
        now = datetime.now()
        time_diff = abs((now - timestamp).total_seconds())
        
        if time_diff > 300:  # 5 minutes
            warnings.append(
                f"Timestamp is {time_diff:.0f}s old (stale data)"
            )
            metadata["timestamp_age_seconds"] = time_diff
        
        # 3. Validate price change (anomaly detection)
        if source in self._price_history and self._price_history[source]:
            last_price = self._price_history[source][-1]
            change_percent = abs((price - last_price) / last_price) * 100
            
            if change_percent > price_rule.max_change_percent:
                warnings.append(
                    f"Large price change: {change_percent:.2f}% "
                    f"(from ${last_price:,.2f} to ${price:,.2f})"
                )
                metadata["price_change_percent"] = float(change_percent)
        
        # 4. Validate bid/ask spread
        if bid and ask:
            spread = ask - bid
            spread_percent = (spread / bid) * 100
            
            if spread_percent > 1.0:  # > 1% spread is unusual for BTC
                warnings.append(
                    f"Wide bid/ask spread: {spread_percent:.2f}% "
                    f"(${spread:,.2f})"
                )
                metadata["spread_percent"] = float(spread_percent)
            
            if bid > ask:  # Should never happen
                errors.append(
                    f"Bid ${bid:,.2f} > Ask ${ask:,.2f} (crossed market)"
                )
        
        # 5. Validate volume (if provided)
        if volume is not None:
            volume_rule = self.btc_rules["volume"]
            
            if volume < volume_rule.min_value:
                errors.append(f"Negative volume: ${volume:,.2f}")
        
        # Update price history
        if source not in self._price_history:
            self._price_history[source] = []
        
        self._price_history[source].append(price)
        
        # Limit history size
        if len(self._price_history[source]) > self._max_history_size:
            self._price_history[source].pop(0)
        
        # Build result
        is_valid = len(errors) == 0
        
        if errors:
            logger.error(f"Validation FAILED for {source}: {errors}")
        
        if warnings:
            logger.warning(f"Validation warnings for {source}: {warnings}")
        
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            metadata=metadata,
        )
    
    def validate_sentiment_data(
        self,
        score: float,
        timestamp: datetime,
    ) -> ValidationResult:
        """
        Validate sentiment data.
        
        Args:
            score: Sentiment score (0-100)
            timestamp: Data timestamp
            
        Returns:
            ValidationResult
        """
        errors = []
        warnings = []
        metadata = {}
        
        # Validate score range
        if score < 0 or score > 100:
            errors.append(f"Sentiment score {score} out of range [0-100]")
        
        # Validate timestamp
        now = datetime.now()
        time_diff = abs((now - timestamp).total_seconds())
        
        if time_diff > 3600:  # 1 hour
            warnings.append(f"Sentiment data is {time_diff/3600:.1f}h old")
        
        is_valid = len(errors) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            metadata=metadata,
        )
    
    def detect_anomaly(
        self,
        source: str,
        current_price: Decimal,
        z_score_threshold: float = 3.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Detect price anomalies using Z-score.
        
        Args:
            source: Data source
            current_price: Current price to check
            z_score_threshold: Z-score threshold for anomaly
            
        Returns:
            Anomaly details if detected, None otherwise
        """
        if source not in self._price_history:
            return None
        
        history = self._price_history[source]
        
        if len(history) < 10:  # Need enough data
            return None
        
        # Calculate mean and std dev
        mean = sum(history) / len(history)
        variance = sum((x - mean) ** 2 for x in history) / len(history)
        std_dev = Decimal(str(float(variance) ** 0.5))
        
        if std_dev == 0:
            return None
        
        # Calculate Z-score
        z_score = abs((current_price - mean) / std_dev)
        
        if float(z_score) > z_score_threshold:
            return {
                "source": source,
                "current_price": float(current_price),
                "mean_price": float(mean),
                "std_dev": float(std_dev),
                "z_score": float(z_score),
                "threshold": z_score_threshold,
                "anomaly_type": "price_spike" if current_price > mean else "price_drop",
            }
        
        return None
    
    def get_price_statistics(self, source: str) -> Optional[Dict[str, Any]]:
        """
        Get price statistics for a source.
        
        Args:
            source: Data source
            
        Returns:
            Statistics dict or None
        """
        if source not in self._price_history or not self._price_history[source]:
            return None
        
        history = self._price_history[source]
        
        mean = sum(history) / len(history)
        min_price = min(history)
        max_price = max(history)
        current_price = history[-1]
        
        return {
            "source": source,
            "count": len(history),
            "current": float(current_price),
            "mean": float(mean),
            "min": float(min_price),
            "max": float(max_price),
            "range": float(max_price - min_price),
            "range_percent": float((max_price - min_price) / min_price * 100),
        }
    
    def clear_history(self, source: Optional[str] = None) -> None:
        """
        Clear price history.
        
        Args:
            source: Specific source to clear, or None for all
        """
        if source:
            if source in self._price_history:
                self._price_history[source].clear()
                logger.info(f"Cleared price history for {source}")
        else:
            self._price_history.clear()
            logger.info("Cleared all price history")


# Singleton instance
_validator_instance: Optional[DataValidator] = None

def get_validator() -> DataValidator:
    """Get singleton instance of data validator."""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = DataValidator()
    return _validator_instance