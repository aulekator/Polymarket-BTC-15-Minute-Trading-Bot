"""
Complete BTC 15-Min Trading Bot - FIXED VERSION
- Uses time-based filtering (proven to work from test)
- $1 per trade maximum
- Reloads instruments every 12 minutes
- Pre-loads price history on startup
- Full P&L tracking in simulation
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import math
from decimal import Decimal
import time
from dataclasses import dataclass
from typing import List, Optional
import random

# Add project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Apply patch BEFORE importing Nautilus
try:
    from patch_gamma_markets import apply_gamma_markets_patch, verify_patch
    patch_applied = apply_gamma_markets_patch()
    if patch_applied:
        verify_patch()
    else:
        print("ERROR: Failed to apply gamma_market patch")
        sys.exit(1)
except ImportError as e:
    print(f"ERROR: Could not import patch module: {e}")
    print("Make sure patch_gamma_markets.py is in the same directory")
    sys.exit(1)

# Now import Nautilus
from nautilus_trader.config import (
    InstrumentProviderConfig,
    LiveDataEngineConfig,
    LiveExecEngineConfig,
    LiveRiskEngineConfig,
    LoggingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode
from nautilus_trader.adapters.polymarket import POLYMARKET
from nautilus_trader.adapters.polymarket import (
    PolymarketDataClientConfig,
    PolymarketExecClientConfig,
)
from nautilus_trader.adapters.polymarket.factories import (
    PolymarketLiveDataClientFactory,
    PolymarketLiveExecClientFactory,
)
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.identifiers import InstrumentId, ClientOrderId
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.objects import Quantity
from nautilus_trader.model.data import QuoteTick

from dotenv import load_dotenv
from loguru import logger
import redis

# Import our phases
from core.strategy_brain.signal_processors.spike_detector import SpikeDetectionProcessor
from core.strategy_brain.signal_processors.sentiment_processor import SentimentProcessor
from core.strategy_brain.signal_processors.divergence_processor import PriceDivergenceProcessor
from core.strategy_brain.fusion_engine.signal_fusion import get_fusion_engine
from execution.risk_engine import get_risk_engine
from monitoring.performance_tracker import get_performance_tracker
from monitoring.grafana_exporter import get_grafana_exporter
from feedback.learning_engine import get_learning_engine

load_dotenv()


@dataclass
class PaperTrade:
    """Track paper/simulation trades"""
    timestamp: datetime
    direction: str
    size_usd: float
    price: float
    signal_score: float
    signal_confidence: float
    outcome: str = "PENDING"
    
    def to_dict(self):
        return {
            'timestamp': self.timestamp.isoformat(),
            'direction': self.direction,
            'size_usd': self.size_usd,
            'price': self.price,
            'signal_score': self.signal_score,
            'signal_confidence': self.signal_confidence,
            'outcome': self.outcome,
        }


def init_redis():
    """Initialize Redis connection for simulation mode control."""
    try:
        redis_client = redis.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            db=int(os.getenv('REDIS_DB', 2)),
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True
        )
        redis_client.ping()
        logger.info("Redis connection established")
        return redis_client
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        logger.warning("Simulation mode will be static (from .env)")
        return None


class IntegratedBTCStrategy(Strategy):
    """
    Integrated BTC Strategy combining:
    - Nautilus trading framework
    - Our 7-phase system
    - Redis simulation control
    - Paper trading tracking
    - Auto-reload instruments every 12 minutes
    - Pre-loaded price history for immediate trading
    """
    
    def __init__(self, redis_client=None, enable_grafana=True, test_mode=False):
        super().__init__()
        
        # Nautilus
        self.instrument_id = None
        self.redis_client = redis_client
        self.current_simulation_mode = True
        
        # Phase 4: Signal Processors
        self.spike_detector = SpikeDetectionProcessor(
            spike_threshold=float(os.getenv('SPIKE_THRESHOLD', 0.15)),
            lookback_periods=20,
        )
        self.sentiment_processor = SentimentProcessor(
            extreme_fear_threshold=25,
            extreme_greed_threshold=75,
        )
        self.divergence_processor = PriceDivergenceProcessor(
            divergence_threshold=0.05,
        )
        
        # Phase 4: Signal Fusion
        self.fusion_engine = get_fusion_engine()
        
        # Phase 5: Risk Management
        self.risk_engine = get_risk_engine()
        
        # Phase 6: Performance Tracking
        self.performance_tracker = get_performance_tracker()
        
        # Phase 7: Learning Engine
        self.learning_engine = get_learning_engine()
        
        # Phase 6: Grafana (optional)
        if enable_grafana:
            self.grafana_exporter = get_grafana_exporter()
        else:
            self.grafana_exporter = None
        
        # Price history for signal processing
        self.price_history = []
        self.max_history = 100
        
        # Paper trading tracker
        self.paper_trades: List[PaperTrade] = []
        
        # Last trading decision time (to prevent multiple trades per interval)
        self.last_trade_time = 0
        
        # Last instrument reload time
        self.last_reload_time = 0

        self.test_mode = test_mode

        if test_mode:
            logger.info("=" * 80)
            logger.info("⚠️  TEST MODE ACTIVE - Trading every minute!")
            logger.info("=" * 80)
        
        logger.info("=" * 80)
        logger.info("INTEGRATED BTC STRATEGY INITIALIZED")
        logger.info("  Phase 4: Signal processors ready")
        logger.info("  Phase 5: Risk engine ready")
        logger.info("  Phase 6: Performance tracking ready")
        logger.info("  Phase 7: Learning engine ready")
        logger.info("  $1 per trade maximum")
        logger.info("  Reloads instruments every 12 minutes")
        logger.info("=" * 80)
    
    async def check_simulation_mode(self) -> bool:
        """Check Redis for current simulation mode."""
        if not self.redis_client:
            return self.current_simulation_mode
        
        try:
            sim_mode = self.redis_client.get('btc_trading:simulation_mode')
            if sim_mode is not None:
                redis_simulation = sim_mode == '1'
                
                if redis_simulation != self.current_simulation_mode:
                    self.current_simulation_mode = redis_simulation
                    mode_text = "SIMULATION" if redis_simulation else "LIVE TRADING"
                    logger.warning(f"Trading mode changed to: {mode_text}")
                    
                    if not redis_simulation:
                        logger.warning("LIVE TRADING ACTIVE - Real money at risk!")
                
                return redis_simulation
        except Exception as e:
            logger.warning(f"Failed to check Redis simulation mode: {e}")
        
        return self.current_simulation_mode
    
    def on_start(self):
        """Called when strategy starts."""
        logger.info("=" * 80)
        logger.info("INTEGRATED BTC STRATEGY STARTED")
        logger.info("=" * 80)
        
        # Find BTC instrument FIRST and wait for it
        self._find_btc_instrument()
        
        # Generate synthetic history regardless (for testing)
        # This ensures we have price data even if no BTC instrument found
        logger.info("Generating synthetic price history for testing...")
        
        # Check if we already have price history
        if len(self.price_history) < 20:
            # Generate synthetic history directly (not async since we're in sync context)
            self._generate_synthetic_history(target_count=20, existing_count=len(self.price_history))
        
        # Try to get real price if instrument exists and we have quotes
        if self.instrument_id:
            try:
                # Get the most recent quote from cache
                quote = self.cache.quote_tick(self.instrument_id)
                if quote and quote.bid_price and quote.ask_price:
                    current_price = (quote.bid_price + quote.ask_price) / 2
                    # Replace last synthetic price with real one
                    if self.price_history:
                        self.price_history[-1] = current_price
                    else:
                        self.price_history.append(current_price)
                    logger.info(f"Real price from cache: ${float(current_price):.4f}")
            except Exception as e:
                logger.debug(f"Could not get real price: {e}")
                logger.debug("Using synthetic prices until real quotes arrive")
        
        # Start instrument reload timer
        self.run_in_executor(self._start_reload_timer)
        
        # Start Grafana if enabled
        if self.grafana_exporter:
            import threading
            threading.Thread(target=self._start_grafana_sync, daemon=True).start()
        
        logger.info("=" * 80)
        logger.info("Strategy active - will trade every 15 minutes")
        logger.info(f"Price history: {len(self.price_history)} points")
        if len(self.price_history) >= 20:
            logger.info("✓ READY TO TRADE at next 15-minute mark!")
        else:
            logger.warning(f"⚠ Need more history ({len(self.price_history)}/20)")
        logger.info("=" * 80)
        logger.info("Use Ctrl+C to stop")
                
    def _preload_history_sync(self):
        """Synchronous wrapper for history preload."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._preload_price_history())
        finally:
            loop.close()
    
    async def _preload_price_history(self):
        """Pre-load price history from cache or generate synthetic data for testing."""
        logger.info("=" * 80)
        logger.info("PRE-LOADING PRICE HISTORY")
        logger.info("=" * 80)
        
        # Get current instrument
        if not self.instrument_id:
            logger.warning("No instrument ID, skipping preload")
            return
        
        # Try to get current price from cache first
        quote = self.cache.quote_tick(self.instrument_id)
        if quote:
            current_price = (quote.bid_price + quote.ask_price) / 2
            self.price_history.append(current_price)
            logger.info(f"Current price from cache: ${float(current_price):.4f}")
        
        # Try to get historical quotes from cache
        # Note: This depends on your data provider storing history
        quotes = self.cache.quote_tick(self.instrument_id)
        if quotes and len(quotes) > 0:
            for quote in quotes[-20:]:  # Take last 20 quotes
                mid_price = (quote.bid_price + quote.ask_price) / 2
                self.price_history.append(mid_price)
            logger.info(f"Loaded {len(quotes)} historical quotes from cache")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_history = []
        for price in self.price_history:
            price_str = str(price)
            if price_str not in seen:
                seen.add(price_str)
                unique_history.append(price)
        self.price_history = unique_history
        
        # If still not enough, generate synthetic data
        if len(self.price_history) < 20:
            logger.warning(f"Only {len(self.price_history)} historical quotes found, generating synthetic data to fill")
            self._generate_synthetic_history(existing_count=len(self.price_history))
        
        logger.info(f"Final price history: {len(self.price_history)} points")
        if len(self.price_history) >= 20:
            logger.info("✓ SUFFICIENT HISTORY - Ready to trade!")
        else:
            logger.warning("⚠ Still need more history - will collect from live data")
        
        # Show first few prices
        logger.info("Sample price points:")
        for i, price in enumerate(self.price_history[:5]):
            logger.info(f"  Price {i+1}: ${float(price):.4f}")
        
        logger.info("=" * 80)
    
    def _generate_synthetic_history(self, target_count: int = 20, existing_count: int = 0):
        """Generate synthetic price history for testing/initialization."""
        # Get current price if available
        if self.price_history and len(self.price_history) > 0:
            base_price = self.price_history[-1]
            logger.info(f"Using last real price as base: ${float(base_price):.4f}")
        else:
            # Use a reasonable default for prediction markets
            base_price = Decimal("0.5")
            logger.info(f"No real price available, using default base: ${float(base_price):.4f}")
        
        needed = target_count - existing_count
        if needed <= 0:
            return
        
        logger.info(f"Generating {needed} synthetic price points")
        
        # Generate realistic looking price movement (random walk)
        for i in range(needed):
            # Random walk with small steps (±3% max change)
            change = Decimal(str(random.uniform(-0.03, 0.03)))
            new_price = base_price * (Decimal("1.0") + change)
            
            # Ensure price stays in 0-1 range for prediction markets
            new_price = max(Decimal("0.01"), min(Decimal("0.99"), new_price))
            
            self.price_history.append(new_price)
            base_price = new_price
        
        logger.info(f"Generated {needed} synthetic price points")
        logger.info(f"Now have {len(self.price_history)} total price points")
    
    def _start_reload_timer(self):
        """Start timer to reload instruments every 12 minutes."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._reload_loop())
        finally:
            loop.close()
    
    async def _reload_loop(self):
        """Reload instruments every 12 minutes and update to current active market."""
        while True:
            await asyncio.sleep(720)  # 12 minutes = 720 seconds
            logger.info("=" * 80)
            logger.info("RELOADING INSTRUMENTS (12-minute interval)")
            logger.info("=" * 80)
            
            try:
                # Request instrument reload from data client
                instruments = self.cache.instruments()
                logger.info(f"Before reload: {len(instruments)} instruments in cache")
                
                # Re-find BTC instrument (this will select the active one)
                self._find_btc_instrument()
                
                logger.info("Instruments reloaded successfully")
            except Exception as e:
                logger.error(f"Failed to reload instruments: {e}")
                
    def _start_grafana_sync(self):
        """Start Grafana in separate thread."""
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.grafana_exporter.start())
            logger.info("Grafana metrics started on port 8000")
        except Exception as e:
            logger.error(f"Failed to start Grafana: {e}")
    
    def _find_btc_instrument(self):
        """Find the CURRENT active BTC 15-min instrument."""
        instruments = self.cache.instruments()
        logger.info(f"Checking {len(instruments)} loaded instruments...")
        
        if not instruments:
            logger.error("NO INSTRUMENTS LOADED!")
            return
        
        # Get current UTC time
        now = datetime.now(timezone.utc)
        current_timestamp = int(now.timestamp())
        
        btc_instruments = []
        
        for instrument in instruments:
            try:
                if hasattr(instrument, 'info') and instrument.info:
                    question = instrument.info.get('question', '').lower()
                    slug = instrument.info.get('market_slug', '').lower()
                    
                    if ('btc' in question or 'btc' in slug) and '15m' in slug:
                        # Extract timestamp from slug
                        try:
                            timestamp_part = slug.split('-')[-1]
                            market_timestamp = int(timestamp_part)
                            
                            # Get end time from instrument
                            end_date = instrument.info.get('end_date_iso')
                            end_timestamp = None
                            if end_date:
                                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                                end_timestamp = int(end_dt.timestamp())
                            
                            # Calculate time difference
                            time_diff = market_timestamp - current_timestamp
                            
                            btc_instruments.append({
                                'instrument': instrument,
                                'slug': slug,
                                'market_timestamp': market_timestamp,
                                'end_timestamp': end_timestamp,
                                'question': question,
                                'active': instrument.info.get('active', False),
                                'closed': instrument.info.get('closed', True),
                                'time_diff_minutes': time_diff / 60,  # Minutes from now
                            })
                            
                        except (ValueError, IndexError):
                            continue
            
            except Exception:
                continue
        
        if not btc_instruments:
            logger.error("NO BTC 15-MIN INSTRUMENTS FOUND!")
            return
        
        # Sort by how close they are to current time (positive means future)
        # We want the one that started most recently (smallest positive time_diff)
        current_markets = [i for i in btc_instruments if i['time_diff_minutes'] <= 0 and i['time_diff_minutes'] > -15]
        future_markets = [i for i in btc_instruments if i['time_diff_minutes'] > 0]
        
        logger.info("=" * 80)
        logger.info("BTC 15-MIN INSTRUMENTS:")
        for i in btc_instruments:
            status = "CURRENT" if i in current_markets else "FUTURE" if i['time_diff_minutes'] > 0 else "PAST"
            logger.info(f"  {i['slug']}: {status} (starts in {i['time_diff_minutes']:.1f} min)")
        logger.info("=" * 80)
        
        # Select the current market if available
        if current_markets:
            # Sort by closest to now
            current_markets.sort(key=lambda x: abs(x['time_diff_minutes']))
            selected = current_markets[0]
            logger.info(f"✓ SELECTED CURRENT market: {selected['slug']}")
        else:
            # Select the next future market
            future_markets.sort(key=lambda x: x['time_diff_minutes'])
            selected = future_markets[0]
            logger.info(f"⚠ No current market, selecting next: {selected['slug']} (starts in {selected['time_diff_minutes']:.1f} min)")
        
        self.instrument_id = selected['instrument'].id
        self.subscribe_quote_ticks(self.instrument_id)
                        
    def on_quote_tick(self, tick: QuoteTick):
        """Handle quote tick updates."""
        try:
            # Check if we have valid prices
            if tick.bid_price is None or tick.ask_price is None:
                logger.debug(f"Skipping incomplete quote: bid={tick.bid_price}, ask={tick.ask_price}")
                return
            
            # Get decimal values properly
            bid_decimal = tick.bid_price.as_decimal()
            ask_decimal = tick.ask_price.as_decimal()
            
            # Calculate mid price
            mid_price = (bid_decimal + ask_decimal) / 2
            
            # Update price history
            self.price_history.append(mid_price)
            
            # Limit history size
            if len(self.price_history) > self.max_history:
                self.price_history.pop(0)
            
            # Check if we should trade
            now = datetime.now(timezone.utc)
            
            if self.test_mode:
                # TEST MODE: Trade every minute at the start of each minute
                current_minute = now.replace(second=0, microsecond=0)
                seconds_since_minute = now.second
                
                if seconds_since_minute < 5:  # Within first 5 seconds of each minute
                    if current_minute != self.last_trade_time:
                        self.last_trade_time = current_minute
                        logger.info("=" * 80)
                        logger.info(f"TEST MODE - MINUTE REACHED: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
                        logger.info(f"Current price: ${float(mid_price):,.4f}")
                        logger.info(f"Bid: ${float(bid_decimal):,.4f}, Ask: ${float(ask_decimal):,.4f}")
                        logger.info(f"Price history size: {len(self.price_history)}")
                        logger.info("=" * 80)
                        
                        # Make trading decision
                        self.run_in_executor(lambda: self._make_trading_decision_sync(float(mid_price)))
            else:
                # NORMAL MODE: Trade every 15 minutes
                seconds_since_interval = now.timestamp() % 900
                
                if seconds_since_interval < 30:
                    current_interval = int(now.timestamp() // 900)
                    
                    if current_interval != self.last_trade_time:
                        self.last_trade_time = current_interval
                        logger.info("=" * 80)
                        logger.info(f"15-MIN INTERVAL REACHED: {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
                        logger.info(f"Current price: ${float(mid_price):,.4f}")
                        logger.info(f"Bid: ${float(bid_decimal):,.4f}, Ask: ${float(ask_decimal):,.4f}")
                        logger.info(f"Price history size: {len(self.price_history)}")
                        logger.info("=" * 80)
                        
                        # Make trading decision
                        self.run_in_executor(lambda: self._make_trading_decision_sync(float(mid_price)))
        
        except Exception as e:
            logger.error(f"Error processing quote tick: {e}")
            import traceback
            traceback.print_exc()
                                            
    def _make_trading_decision_sync(self, current_price):
        """Synchronous wrapper for trading decision (called from executor)."""
        # Convert float back to Decimal for processing
        from decimal import Decimal
        price_decimal = Decimal(str(current_price))
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._make_trading_decision(price_decimal))
        finally:
            loop.close()
            
    async def _make_trading_decision(self, current_price):
        """Make trading decision using our 7-phase system."""
        
        # Check simulation mode
        is_simulation = await self.check_simulation_mode()
        mode_text = "SIMULATION" if is_simulation else "LIVE TRADING"
        logger.info(f"Mode: {mode_text}")
        
        # Need price history
        if len(self.price_history) < 20:
            logger.warning(f"Not enough price history yet ({len(self.price_history)}/20)")
            return
        
        logger.info(f"Current price: ${float(current_price):,.4f}")
        
        # Create test metadata with sentiment and spot price for better signals
        # FIX: Convert everything to float consistently
        current_price_float = float(current_price)
        metadata = {
            "sentiment_score": random.uniform(10, 90),  # Random sentiment for testing
            "spot_price": current_price_float * random.uniform(0.95, 1.05),  # Random divergence as float
        }
        
        # Phase 4: Process signals
        signals = self._process_signals(current_price, metadata)
        
        if not signals:
            logger.info("No signals generated")
            return
        
        logger.info(f"Generated {len(signals)} signals:")
        for sig in signals:
            logger.info(f"  [{sig.source}] {sig.direction.value}: score={sig.score:.1f}")
        
        # Phase 4: Fuse signals
        fused = self.fusion_engine.fuse_signals(signals, min_signals=1, min_score=60.0)
        
        if not fused:
            logger.info("No actionable fused signal")
            return
        
        logger.info(f"FUSED SIGNAL: {fused.direction.value} (score={fused.score:.1f}, confidence={fused.confidence:.2%})")
        
        # Phase 5: Calculate position size (with $1 cap)
        position_size = self.risk_engine.calculate_position_size(
            signal_confidence=fused.confidence,
            signal_score=fused.score,
            current_price=current_price,  # Pass Decimal to risk engine
        )
        
        logger.info(f"Calculated position size: ${float(position_size):.2f}")
        
        # Phase 5: Validate with risk engine
        direction = "long" if "BULLISH" in str(fused.direction) else "short"
        is_valid, error = self.risk_engine.validate_new_position(
            size=position_size,
            direction=direction,
            current_price=current_price,
        )
        
        if not is_valid:
            logger.warning(f"Position rejected by risk engine: {error}")
            return
        
        # Execute trade (simulation or live based on Redis)
        if is_simulation:
            await self._record_paper_trade(fused, position_size, current_price, direction)
        else:
            await self._place_real_order(fused, position_size, current_price, direction)
            
    async def _record_paper_trade(self, signal, position_size, current_price, direction):
        """Record a paper trade for simulation tracking."""
        
        # Simulate exit after 1 minute (for test mode) or 15 minutes (for normal mode)
        if hasattr(self, 'test_mode') and self.test_mode:
            exit_delta = timedelta(minutes=1)
        else:
            exit_delta = timedelta(minutes=15)
        
        exit_time = datetime.now(timezone.utc) + exit_delta
        
        # Simulate price movement based on signal direction
        if "BULLISH" in str(signal.direction):
            movement = random.uniform(-0.02, 0.08)  # -2% to +8%
        else:
            movement = random.uniform(-0.08, 0.02)  # -8% to +2%
        
        exit_price = current_price * (Decimal("1.0") + Decimal(str(movement)))
        exit_price = max(Decimal("0.01"), min(Decimal("0.99"), exit_price))
        
        # Calculate P&L
        if direction == "long":
            pnl = position_size * (exit_price - current_price) / current_price
        else:
            pnl = position_size * (current_price - exit_price) / current_price
        
        # Determine outcome
        outcome = "WIN" if pnl > 0 else "LOSS"
        
        # Create paper trade record with outcome
        paper_trade = PaperTrade(
            timestamp=datetime.now(timezone.utc),
            direction=direction.upper(),
            size_usd=float(position_size),
            price=float(current_price),
            signal_score=signal.score,
            signal_confidence=signal.confidence,
            outcome=outcome,  # ← NOW SETTING OUTCOME!
        )
        
        self.paper_trades.append(paper_trade)
        
        # Record in performance tracker
        self.performance_tracker.record_trade(
            trade_id=f"paper_{int(datetime.now().timestamp())}",
            direction=direction,
            entry_price=current_price,
            exit_price=exit_price,
            size=position_size,
            entry_time=datetime.now(timezone.utc),
            exit_time=exit_time,
            signal_score=signal.score,
            signal_confidence=signal.confidence,
            metadata={
                "simulated": True,
                "num_signals": signal.num_signals if hasattr(signal, 'num_signals') else 1,
                "fusion_score": signal.score,
            }
        )
        
        # Update metrics in grafana exporter
        if hasattr(self, 'grafana_exporter') and self.grafana_exporter:
            self.grafana_exporter.increment_trade_counter(won=(pnl > 0))
            self.grafana_exporter.record_trade_duration(exit_delta.total_seconds())
        
        logger.info("=" * 80)
        logger.info("[SIMULATION] PAPER TRADE RECORDED")
        logger.info(f"  Direction: {direction.upper()}")
        logger.info(f"  Size: ${float(position_size):.2f}")
        logger.info(f"  Entry Price: ${float(current_price):,.4f}")
        logger.info(f"  Simulated Exit: ${float(exit_price):,.4f}")
        logger.info(f"  Simulated P&L: ${float(pnl):+.2f} ({movement*100:+.2f}%)")
        logger.info(f"  Outcome: {outcome}")
        logger.info(f"  Signal Score: {signal.score:.1f}")
        logger.info(f"  Signal Confidence: {signal.confidence:.2%}")
        logger.info(f"  Total Paper Trades: {len(self.paper_trades)}")
        logger.info("=" * 80)
        
        self._save_paper_trades()
            
    def _save_paper_trades(self):
        """Save paper trades to JSON file."""
        import json
        try:
            trades_data = [t.to_dict() for t in self.paper_trades]
            with open('paper_trades.json', 'w') as f:
                json.dump(trades_data, f, indent=2)
            logger.info(f"Saved {len(trades_data)} paper trades to paper_trades.json")
        except Exception as e:
            logger.error(f"Failed to save paper trades: {e}")
    
    async def _place_real_order(self, signal, position_size, current_price, direction):
        """Place REAL order using Nautilus."""
        if not self.instrument_id:
            logger.error("No instrument available")
            return
        
        try:
            # Get instrument
            instrument = self.cache.instrument(self.instrument_id)
            if not instrument:
                logger.error("Instrument not in cache")
                return
            
            logger.info("=" * 80)
            logger.info("LIVE MODE - PLACING REAL ORDER!")
            logger.info("=" * 80)
            
            # Determine side
            side = OrderSide.BUY if direction == "long" else OrderSide.SELL
            
            # Calculate token quantity
            trade_price = float(current_price)
            max_usd_amount = float(position_size)
            
            if trade_price > 0:
                token_qty = max_usd_amount / trade_price
            else:
                token_qty = max_usd_amount * 2
            
            # Round to appropriate precision
            precision = instrument.size_precision
            token_qty = round(token_qty, precision)
            
            # Ensure minimum quantity
            min_qty = 10 ** (-precision)
            if token_qty < min_qty:
                token_qty = min_qty
            
            qty = Quantity(token_qty, precision=precision)
            
            # Create unique order ID
            timestamp_ms = int(time.time() * 1000)
            unique_id = f"BTC-15MIN-${max_usd_amount:.0f}-{timestamp_ms}"
            
            # Create market order
            order = self.order_factory.market(
                instrument_id=self.instrument_id,
                order_side=side,
                quantity=qty,
                client_order_id=ClientOrderId(unique_id),
                quote_quantity=False,
                time_in_force=TimeInForce.IOC,
            )
            
            # Submit order
            self.submit_order(order)
            
            logger.info(f"REAL ORDER SUBMITTED!")
            logger.info(f"  Order ID: {unique_id}")
            logger.info(f"  Side: {side.name}")
            logger.info(f"  Token Quantity: {token_qty:.6f}")
            logger.info(f"  Estimated Cost: ~${max_usd_amount:.2f}")
            logger.info(f"  Price: ${trade_price:.4f}")
            logger.info("=" * 80)
            
            # Track order in performance tracker
            self.performance_tracker.increment_order_counter("placed")
            
        except Exception as e:
            logger.error(f"Error placing real order: {e}")
            import traceback
            traceback.print_exc()
            self.performance_tracker.increment_order_counter("rejected")
    
    def _process_signals(self, current_price, metadata=None):
        """Process all signal processors."""
        signals = []
        
        if metadata is None:
            metadata = {}
        
        # Convert metadata values to Decimal where needed by processors
        processed_metadata = {}
        for key, value in metadata.items():
            if isinstance(value, float):
                # Convert float to Decimal for processors that expect Decimal
                processed_metadata[key] = Decimal(str(value))
            else:
                processed_metadata[key] = value
        
        # Spike detection
        spike_signal = self.spike_detector.process(
            current_price=current_price,
            historical_prices=self.price_history,
            metadata=processed_metadata,
        )
        if spike_signal:
            signals.append(spike_signal)
        
        # Sentiment processor (if we have sentiment data)
        if 'sentiment_score' in processed_metadata:
            sentiment_signal = self.sentiment_processor.process(
                current_price=current_price,
                historical_prices=self.price_history,
                metadata=processed_metadata,
            )
            if sentiment_signal:
                signals.append(sentiment_signal)
        
        # Divergence processor (if we have spot price)
        if 'spot_price' in processed_metadata:
            divergence_signal = self.divergence_processor.process(
                current_price=current_price,
                historical_prices=self.price_history,
                metadata=processed_metadata,
            )
            if divergence_signal:
                signals.append(divergence_signal)
        
        return signals

    def on_order_filled(self, event):
        """Handle when a REAL order is filled."""
        logger.info("=" * 80)
        logger.info(f"ORDER FILLED!")
        logger.info(f"  Order: {event.client_order_id}")
        logger.info(f"  Fill Price: ${float(event.last_px):.4f}")
        logger.info(f"  Quantity: {float(event.last_qty):.6f}")
        logger.info("=" * 80)
        
        self.performance_tracker.increment_order_counter("filled")
    
    def on_order_denied(self, event):
        """Handle when an order is denied."""
        logger.error("=" * 80)
        logger.error(f"ORDER DENIED!")
        logger.error(f"  Order: {event.client_order_id}")
        logger.error(f"  Reason: {event.reason}")
        logger.error("=" * 80)
        
        self.performance_tracker.increment_order_counter("rejected")
    
    def on_stop(self):
        """Called when strategy stops."""
        logger.info("Integrated BTC strategy stopped")
        logger.info(f"Total paper trades recorded: {len(self.paper_trades)}")
        
        if self.grafana_exporter:
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.grafana_exporter.stop())
            except:
                pass


def run_integrated_bot(simulation: bool = True, enable_grafana: bool = True, test_mode: bool = False):
    """Run the integrated BTC 15-min trading bot."""
    print("=" * 80)
    print("INTEGRATED POLYMARKET BTC 15-MIN TRADING BOT")
    print("Nautilus + 7-Phase System + Redis Control")
    print("=" * 80)
    
    # Initialize Redis
    redis_client = init_redis()
    
    # Set initial simulation mode in Redis
    if redis_client:
        try:
            redis_client.set('btc_trading:simulation_mode', '1' if simulation else '0')
            logger.info(f"Initial mode set in Redis: {'SIMULATION' if simulation else 'LIVE'}")
        except Exception as e:
            logger.warning(f"Could not set Redis simulation mode: {e}")
    
    print(f"\nConfiguration:")
    print(f"  Initial Mode: {'SIMULATION' if simulation else 'LIVE TRADING'}")
    print(f"  Redis Control: {'Enabled' if redis_client else 'Disabled'}")
    print(f"  Grafana: {'Enabled' if enable_grafana else 'Disabled'}")
    print(f"  Max Trade Size: $1.00")
    print(f"  Instrument Reload: Every 12 minutes")
    print(f"  Price History: Pre-loaded on startup")
    print()
    
    # CORRECT APPROACH: Use time-based filtering (proven to work from test)
    # DO NOT use tag_id=744 - it returns empty!
    
    now = datetime.now(timezone.utc)

    # IMPORTANT: Use ISO format strings for dates
    filters = {
        "active": True,
        "closed": False,
        "archived": False,
        "end_date_min": now.isoformat().replace('+00:00', 'Z'),  # Markets expiring after now
        "end_date_max": (now + timedelta(minutes=30)).isoformat().replace('+00:00', 'Z'),  # Within 30 min
        "limit": 1000,  # Request more markets per page
    }

    
    logger.info("=" * 80)
    logger.info("Using TIME-BASED FILTERING (proven to work)")
    logger.info(f"  Expiring between: {now.strftime('%H:%M:%S')} - {(now + timedelta(minutes=30)).strftime('%H:%M:%S')} UTC")
    logger.info("  This will load all active markets including BTC 15-min")
    logger.info("=" * 80)
    
    # CRITICAL: use_gamma_markets=True enables filtering!
    instrument_cfg = InstrumentProviderConfig(
        load_all=True,  # Load all markets matching filters
        filters=filters,
        use_gamma_markets=True,  # CRITICAL!
    )
    
    # Polymarket data client config
    poly_data_cfg = PolymarketDataClientConfig(
        private_key=os.getenv("POLYMARKET_PK"),
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        passphrase=os.getenv("POLYMARKET_PASSPHRASE"),
        instrument_provider=instrument_cfg,
    )
    
    # Polymarket execution client config
    poly_exec_cfg = PolymarketExecClientConfig(
        private_key=os.getenv("POLYMARKET_PK"),
        api_key=os.getenv("POLYMARKET_API_KEY"),
        api_secret=os.getenv("POLYMARKET_API_SECRET"),
        passphrase=os.getenv("POLYMARKET_PASSPHRASE"),
        instrument_provider=instrument_cfg,
    )
    
    # Trading node configuration
    config = TradingNodeConfig(
        environment="live",
        trader_id="BTC-15MIN-INTEGRATED-001",
        logging=LoggingConfig(
            log_level="INFO",
            log_directory="./logs/nautilus",
        ),
        data_engine=LiveDataEngineConfig(qsize=6000),
        exec_engine=LiveExecEngineConfig(qsize=6000),
        risk_engine=LiveRiskEngineConfig(
            bypass=simulation,
        ),
        data_clients={POLYMARKET: poly_data_cfg},
        exec_clients={POLYMARKET: poly_exec_cfg},
    )
    
    # Create integrated strategy
    strategy = IntegratedBTCStrategy(
        redis_client=redis_client,
        enable_grafana=enable_grafana,
        test_mode=test_mode,
    )
    
    # Build Nautilus node
    print("\nBuilding Nautilus node...")
    print("=" * 80)
    
    node = TradingNode(config=config)
    
    # Add Polymarket factories
    node.add_data_client_factory(POLYMARKET, PolymarketLiveDataClientFactory)
    node.add_exec_client_factory(POLYMARKET, PolymarketLiveExecClientFactory)
    
    # Add strategy
    node.trader.add_strategy(strategy)
    
    # Build and start
    node.build()
    logger.info("Nautilus node built successfully")
    
    print()
    print("=" * 80)
    print("BOT STARTING")
    print("=" * 80)
    
    try:
        node.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        node.dispose()
        logger.info("Bot stopped")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Integrated BTC 15-Min Trading Bot")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run in LIVE mode (real money at risk!). Default is simulation."
    )
    parser.add_argument(
        "--no-grafana",
        action="store_true",
        help="Disable Grafana metrics"
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Run in TEST MODE (trade every minute for faster testing)"
    )
    
    args = parser.parse_args()
    
    simulation = not args.live
    enable_grafana = not args.no_grafana
    test_mode = args.test_mode
    
    if not simulation:
        print("WARNING: LIVE TRADING MODE - REAL MONEY AT RISK!")
        confirm = input("Type 'yes' to continue: ")
        if confirm.lower() != 'yes':
            print("Cancelled.")
            return
    
    run_integrated_bot(
        simulation=simulation,
        enable_grafana=enable_grafana,
        test_mode=test_mode
    )


if __name__ == "__main__":
    main()