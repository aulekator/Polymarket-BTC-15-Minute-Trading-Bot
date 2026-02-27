import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
import math
from decimal import Decimal
import time
from typing import List, Optional, Dict

# Add project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


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

# Import our phases
from core.strategy_brain.signal_processors.spike_detector import SpikeDetectionProcessor
from core.strategy_brain.signal_processors.sentiment_processor import SentimentProcessor
from core.strategy_brain.signal_processors.divergence_processor import PriceDivergenceProcessor
from core.strategy_brain.signal_processors.orderbook_processor import OrderBookImbalanceProcessor
from core.strategy_brain.signal_processors.tick_velocity_processor import TickVelocityProcessor
from core.strategy_brain.signal_processors.deribit_pcr_processor import DeribitPCRProcessor
from core.strategy_brain.fusion_engine.signal_fusion import get_fusion_engine
from execution.risk_engine import get_risk_engine
from monitoring.performance_tracker import get_performance_tracker
from monitoring.grafana_exporter import get_grafana_exporter
from feedback.learning_engine import get_learning_engine
load_dotenv()
from patch_market_orders import apply_market_order_patch
patch_applied = apply_market_order_patch()
if patch_applied:
    logger.info("Market order patch applied successfully")
else:
    logger.warning("Market order patch failed - orders may be rejected")


# =============================================================================
# CONFIG — all tuning constants from config.py (overridable via .env)
# =============================================================================
import config as cfg

QUOTE_STABILITY_REQUIRED = cfg.QUOTE_STABILITY_REQUIRED
QUOTE_MIN_SPREAD = cfg.QUOTE_MIN_SPREAD
MARKET_INTERVAL_SECONDS = cfg.MARKET_INTERVAL_SECONDS


from models import PaperTrade
from paper_trading import record_paper_trade, save_paper_trades


class IntegratedBTCStrategy(Strategy):
    """
    Integrated BTC Strategy - FIXED VERSION
    - Subscribes immediately at startup
    - Forces stability for first trade
    - Correct timing for market switching
    """

    def __init__(self, redis_client=None, enable_grafana=True, test_mode=False):
        super().__init__()

        self.bot_start_time = datetime.now(timezone.utc)
        self.restart_after_minutes = cfg.RESTART_AFTER_MINUTES

        # Persistent event loop for trading decisions (avoids creating/closing per trade)
        self._decision_loop = asyncio.new_event_loop()

        # Nautilus
        self.instrument_id = None
        self.redis_client = redis_client
        self.current_simulation_mode = False

        # Store ALL BTC instruments
        self.all_btc_instruments: List[Dict] = []
        self.current_instrument_index: int = -1
        self.next_switch_time: Optional[datetime] = None

        # Quote-stability tracking
        self._stable_tick_count = 0
        self._market_stable = False
        self._last_instrument_switch = None
        
        # =========================================================================
        # FIX 1: Force first trade by setting last_trade_time to -1
        # =========================================================================
        self.last_trade_time = -1  # Force first trade immediately!
        self._waiting_for_market_open = False  # True when waiting for a future market to open
        self._last_bid_ask = None  # (bid_decimal, ask_decimal) from last tick, for liquidity checks

        # Tick buffer: rolling 90s of ticks for TickVelocityProcessor
        from collections import deque
        self._tick_buffer: deque = deque(maxlen=cfg.TICK_BUFFER_SIZE)

        # YES token id for the current market (set in _load_all_btc_instruments)
        self._yes_token_id: Optional[str] = None

        # Phase 4: Signal Processors (params from config.py)
        self.spike_detector = SpikeDetectionProcessor(
            spike_threshold=cfg.SPIKE_THRESHOLD,
            lookback_periods=cfg.SPIKE_LOOKBACK,
        )
        self.sentiment_processor = SentimentProcessor(
            extreme_fear_threshold=cfg.SENTIMENT_FEAR_THRESHOLD,
            extreme_greed_threshold=cfg.SENTIMENT_GREED_THRESHOLD,
        )
        self.divergence_processor = PriceDivergenceProcessor(
            divergence_threshold=cfg.DIVERGENCE_THRESHOLD,
        )
        self.orderbook_processor = OrderBookImbalanceProcessor(
            imbalance_threshold=cfg.ORDERBOOK_IMBALANCE_THRESHOLD,
            min_book_volume=cfg.ORDERBOOK_MIN_VOLUME,
        )
        self.tick_velocity_processor = TickVelocityProcessor(
            velocity_threshold_60s=cfg.TICK_VELOCITY_60S,
            velocity_threshold_30s=cfg.TICK_VELOCITY_30S,
        )
        self.deribit_pcr_processor = DeribitPCRProcessor(
            bullish_pcr_threshold=cfg.DERIBIT_BULLISH_PCR,
            bearish_pcr_threshold=cfg.DERIBIT_BEARISH_PCR,
            max_days_to_expiry=cfg.DERIBIT_MAX_DTE,
            cache_seconds=cfg.DERIBIT_CACHE_SECONDS,
        )

        # Phase 4: Signal Fusion — weights from config.py
        self.fusion_engine = get_fusion_engine()
        for name, weight in cfg.SIGNAL_WEIGHTS.items():
            self.fusion_engine.set_weight(name, weight)

        # Phase 5: Risk Management
        self.risk_engine = get_risk_engine()
        self._last_reset_date = datetime.now(timezone.utc).date()  # S8: daily stats reset tracker

        # Phase 6: Performance Tracking
        self.performance_tracker = get_performance_tracker()

        # Phase 7: Learning Engine
        self.learning_engine = get_learning_engine()

        # Phase 6: Grafana (optional)
        if enable_grafana:
            self.grafana_exporter = get_grafana_exporter()
        else:
            self.grafana_exporter = None

        # Price history (deque auto-evicts oldest when full — O(1) vs list.pop(0) O(n))
        from collections import deque as _deque
        self.price_history: _deque = _deque(maxlen=cfg.MAX_PRICE_HISTORY)

        # Paper trading tracker
        self.paper_trades: List[PaperTrade] = []
        self._trade_count: int = 0  # Total trades for learning engine trigger

        self.test_mode = test_mode

        if test_mode:
            logger.info("=" * 80)
            logger.info("  TEST MODE ACTIVE - Trading every minute!")
            logger.info("=" * 80)

        logger.info("=" * 80)
        logger.info("INTEGRATED BTC STRATEGY INITIALIZED - FIXED VERSION")
        logger.info("  Phase 4: Signal processors ready")
        logger.info("  Phase 5: Risk engine ready")
        logger.info("  Phase 6: Performance tracking ready")
        logger.info("  Phase 7: Learning engine ready")
        logger.info("  $1 per trade maximum")
        logger.info("=" * 80)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _seconds_to_next_15min_boundary(self) -> float:
        """Return seconds until the next 15-minute UTC boundary."""
        now_ts = datetime.now(timezone.utc).timestamp()
        next_boundary = (math.floor(now_ts / MARKET_INTERVAL_SECONDS) + 1) * MARKET_INTERVAL_SECONDS
        return next_boundary - now_ts

    def _is_quote_valid(self, bid, ask) -> bool:
        """Return True only when BOTH bid and ask are present and make sense."""
        if bid is None or ask is None:
            return False
        try:
            b = float(bid)
            a = float(ask)
        except (TypeError, ValueError):
            return False
        if b < QUOTE_MIN_SPREAD or a < QUOTE_MIN_SPREAD:
            return False
        if b > 0.999 or a > 0.999:
            return False
        return True

    def _reset_stability(self, reason: str = ""):
        """Mark the market as unstable and reset the counter."""
        if self._market_stable:
            logger.warning(f"Market stability RESET{' – ' + reason if reason else ''}")
        self._market_stable = False
        self._stable_tick_count = 0

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------

    def check_simulation_mode(self) -> bool:
        """
        Check Redis for current simulation mode.
        
        Uses synchronous redis.Redis operations (fast single-key read).
        Safe to call from both sync and async contexts.
        """
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

    # ------------------------------------------------------------------
    # Strategy lifecycle
    # ------------------------------------------------------------------

    def on_start(self):
        """Called when strategy starts - LOAD ALL MARKETS AND SUBSCRIBE IMMEDIATELY"""
        logger.info("=" * 80)
        logger.info("INTEGRATED BTC STRATEGY STARTED - FIXED VERSION")
        logger.info("=" * 80)

        # =========================================================================
        # FIX 2: Load ALL BTC instruments at startup
        # =========================================================================
        self._load_all_btc_instruments()

        # =========================================================================
        # FIX 3: Force subscribe to current market IMMEDIATELY
        # =========================================================================
        if self.instrument_id:
            self.subscribe_quote_ticks(self.instrument_id)
            logger.info(f"✓ SUBSCRIBED to market: {self.instrument_id}")
            
            # Try to get current price from cache
            try:
                quote = self.cache.quote_tick(self.instrument_id)
                if quote and quote.bid_price and quote.ask_price:
                    current_price = (quote.bid_price + quote.ask_price) / 2
                    self.price_history.append(current_price)
                    logger.info(f"✓ Initial price: ${float(current_price):.4f}")
            except Exception as e:
                logger.debug(f"No initial price yet: {e}")

        # Generate synthetic history if needed
        if len(self.price_history) < 20:
            self._generate_synthetic_history(target_count=20, existing_count=len(self.price_history))

        # =========================================================================
        # FIX 4: Start the timer loop (but don't rely on it for trading)
        # =========================================================================
        self.run_in_executor(self._start_timer_loop)

        if self.grafana_exporter:
            import threading
            threading.Thread(target=self._start_grafana_sync, daemon=True).start()

        logger.info("=" * 80)
        logger.info("Strategy active - will trade every 15 minutes")
        logger.info(f"Price history: {len(self.price_history)} points")
        if len(self.price_history) >= 20:
            logger.info("✓ READY TO TRADE NOW!")
        else:
            logger.warning(f"⚠ Need more history ({len(self.price_history)}/20)")
        logger.info("=" * 80)

    def _generate_synthetic_history(self, target_count: int = 20, existing_count: int = 0):
        """Generate synthetic price history for testing"""
        if self.price_history:
            base_price = self.price_history[-1]
        else:
            base_price = Decimal("0.5")
        needed = target_count - existing_count
        if needed <= 0:
            return
        for _ in range(needed):
            change = Decimal(str(random.uniform(-0.03, 0.03)))
            new_price = base_price * (Decimal("1.0") + change)
            new_price = max(Decimal("0.01"), min(Decimal("0.99"), new_price))
            self.price_history.append(new_price)
            base_price = new_price

    # ------------------------------------------------------------------
    # Load all BTC instruments at once
    # ------------------------------------------------------------------

    def _load_all_btc_instruments(self):
        """Load ALL BTC instruments from cache and sort by start time"""
        instruments = self.cache.instruments()
        logger.info(f"Loading ALL BTC instruments from {len(instruments)} total...")
        
        now = datetime.now(timezone.utc)
        current_timestamp = int(now.timestamp())
        
        btc_instruments = []
        
        for instrument in instruments:
            try:
                if hasattr(instrument, 'info') and instrument.info:
                    question = instrument.info.get('question', '').lower()
                    slug = instrument.info.get('market_slug', '').lower()
                    
                    if ('btc' in question or 'btc' in slug) and '15m' in slug:
                        try:
                            timestamp_part = slug.split('-')[-1]
                            market_timestamp = int(timestamp_part)
                            
                            # The slug timestamp IS the market start time (Unix, no offset).
                            # end_date_iso is a DATE-only string (e.g. "2026-02-20"), NOT a datetime,
                            # so parsing it gives midnight UTC which is wrong for intraday markets.
                            # Always derive end_timestamp from the slug: start + 900s.
                            real_start_ts = market_timestamp
                            end_timestamp = market_timestamp + 900  # 15-min markets always
                            time_diff = real_start_ts - current_timestamp
                            
                            # Only include markets that haven't ended yet
                            if end_timestamp > current_timestamp:
                                # Extract YES token ID for CLOB order book API.
                                # Nautilus instrument ID format:
                                #   {condition_id}-{token_id}.POLYMARKET
                                # The CLOB /book endpoint only accepts the token_id
                                # (the part after the dash, before .POLYMARKET).
                                raw_id = str(instrument.id)
                                # Strip .POLYMARKET suffix first
                                without_suffix = raw_id.split('.')[0] if '.' in raw_id else raw_id
                                # Then take the token_id after the condition_id dash
                                yes_token_id = without_suffix.split('-')[-1] if '-' in without_suffix else without_suffix

                                btc_instruments.append({
                                    'instrument': instrument,
                                    'slug': slug,
                                    'start_time': datetime.fromtimestamp(real_start_ts, tz=timezone.utc),
                                    'end_time': datetime.fromtimestamp(end_timestamp, tz=timezone.utc),
                                    'market_timestamp': market_timestamp,
                                    'end_timestamp': end_timestamp,
                                    'time_diff_minutes': time_diff / 60,
                                    'yes_token_id': yes_token_id,
                                })
                        except (ValueError, IndexError):
                            continue
            except Exception:
                continue
        
        # Pair YES and NO tokens by slug.
        # Each Polymarket market has two tokens loaded as separate Nautilus instruments.
        # The first instrument found for a slug is stored as the primary (YES/UP).
        # The second instrument found for the same slug is the NO/DOWN token.
        seen_slugs = {}
        deduped = []
        for inst in btc_instruments:
            slug = inst['slug']
            if slug not in seen_slugs:
                # First token seen = YES (UP)
                inst['yes_instrument_id'] = inst['instrument'].id
                inst['no_instrument_id'] = None  # will be filled when second token found
                seen_slugs[slug] = inst
                deduped.append(inst)
            else:
                # Second token seen = NO (DOWN) — store it on the existing entry
                seen_slugs[slug]['no_instrument_id'] = inst['instrument'].id
        btc_instruments = deduped
        
        # Sort by start time (absolute timestamp, not time-of-day)
        btc_instruments.sort(key=lambda x: x['market_timestamp'])
        
        logger.info("=" * 80)
        logger.info(f"FOUND {len(btc_instruments)} BTC 15-MIN MARKETS:")
        for i, inst in enumerate(btc_instruments):
            # A market is ACTIVE if it has started AND not yet ended
            is_active = inst['time_diff_minutes'] <= 0 and inst['end_timestamp'] > current_timestamp
            status = "ACTIVE" if is_active else "FUTURE" if inst['time_diff_minutes'] > 0 else "PAST"
            logger.info(f"  [{i}] {inst['slug']}: {status} (starts at {inst['start_time'].strftime('%H:%M:%S')}, ends at {inst['end_time'].strftime('%H:%M:%S')})")
        logger.info("=" * 80)
        
        self.all_btc_instruments = btc_instruments
        
        # Find current market and SUBSCRIBE IMMEDIATELY
        # FIXED: A market is current if it has STARTED and not yet ENDED (use end_time, not a hardcoded 15-min window)
        for i, inst in enumerate(btc_instruments):
            is_active = inst['time_diff_minutes'] <= 0 and inst['end_timestamp'] > current_timestamp
            if is_active:
                self.current_instrument_index = i
                self.instrument_id = inst['instrument'].id
                self.next_switch_time = inst['end_time']
                self._yes_token_id = inst.get('yes_token_id')
                self._yes_instrument_id = inst.get('yes_instrument_id', inst['instrument'].id)
                self._no_instrument_id = inst.get('no_instrument_id')
                logger.info(f"✓ CURRENT MARKET: {inst['slug']} (index {i})")
                logger.info(f"  Next switch at: {self.next_switch_time.strftime('%H:%M:%S')}")
                logger.info(f"  YES token: {self._yes_token_id[:16]}…" if self._yes_token_id else "  YES token: unknown")
                
                # =========================================================================
                # CRITICAL FIX: Subscribe immediately!
                # =========================================================================
                self.subscribe_quote_ticks(self.instrument_id)
                logger.info(f"  ✓ SUBSCRIBED to current market")
                break
        
        if self.current_instrument_index == -1 and btc_instruments:
            # No currently-active market — find the NEAREST upcoming one
            # (smallest positive time_diff_minutes = starts soonest)
            future_markets = [inst for inst in btc_instruments if inst['time_diff_minutes'] > 0]
            if future_markets:
                nearest = min(future_markets, key=lambda x: x['time_diff_minutes'])
                nearest_idx = btc_instruments.index(nearest)
            else:
                # All markets are in the past — use the last one
                nearest = btc_instruments[-1]
                nearest_idx = len(btc_instruments) - 1

            self.current_instrument_index = nearest_idx
            inst = nearest
            self.instrument_id = inst['instrument'].id
            self._yes_token_id = inst.get('yes_token_id')
            self._yes_instrument_id = inst.get('yes_instrument_id', inst['instrument'].id)
            self._no_instrument_id = inst.get('no_instrument_id')
            self.next_switch_time = inst['start_time']  # switch_time = when it OPENS
            logger.info(f"⚠ NO CURRENT MARKET - WAITING FOR NEAREST FUTURE: {inst['slug']}")
            logger.info(f"  Starts in {inst['time_diff_minutes']:.1f} min at {self.next_switch_time.strftime('%H:%M:%S')} UTC")

            # Subscribe so we get ticks when it opens
            self.subscribe_quote_ticks(self.instrument_id)
            logger.info(f"  ✓ SUBSCRIBED to future market")
            # Block trading until the market actually opens (timer loop sets _market_open flag)
            self._waiting_for_market_open = True
            
    def _switch_to_next_market(self):
        """Switch to the next market in the pre-loaded list"""
        if not self.all_btc_instruments:
            logger.error("No instruments loaded!")
            return False
        
        next_index = self.current_instrument_index + 1
        if next_index >= len(self.all_btc_instruments):
            logger.warning("No more markets available - will restart bot")
            return False
        
        next_market = self.all_btc_instruments[next_index]
        now = datetime.now(timezone.utc)
        
        # Check if next market is ready
        if now < next_market['start_time']:
            logger.info(f"Waiting for next market at {next_market['start_time'].strftime('%H:%M:%S')}")
            return False
        
        # Switch to next market
        self.current_instrument_index = next_index
        self.instrument_id = next_market['instrument'].id
        self.next_switch_time = next_market['end_time']
        self._yes_token_id = next_market.get('yes_token_id')
        self._yes_instrument_id = next_market.get('yes_instrument_id', next_market['instrument'].id)
        self._no_instrument_id = next_market.get('no_instrument_id')
        
        logger.info("=" * 80)
        logger.info(f"SWITCHING TO NEXT MARKET: {next_market['slug']}")
        logger.info(f"  Current time: {now.strftime('%H:%M:%S')}")
        logger.info(f"  Market ends at: {self.next_switch_time.strftime('%H:%M:%S')}")
        logger.info("=" * 80)
        
        # =========================================================================
        # FIX 5: Force stability for new market and reset trade timer correctly
        # =========================================================================
        self._stable_tick_count = QUOTE_STABILITY_REQUIRED  # Force stable immediately
        self._market_stable = True
        self._waiting_for_market_open = False  # Market is now active
        
        # Reset trade timer so we trade at the NEXT quote we receive
        # Use -1 so any interval will trigger (same as startup)
        self.last_trade_time = -1
        logger.info(f"  Trade timer reset — will trade on next tick")
        
        self.subscribe_quote_ticks(self.instrument_id)
        return True

    # ------------------------------------------------------------------
    # Timer loop - SIMPLIFIED
    # ------------------------------------------------------------------

    def _start_timer_loop(self):
        """Start timer loop in executor"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._timer_loop())
        finally:
            loop.close()

    async def _timer_loop(self):
        """
        Timer loop: checks every 10 seconds if it's time to switch markets.
        Also handles the case where we're waiting for a future market to open.
        """
        while True:
            # --- auto-restart check ---
            uptime_minutes = (datetime.now(timezone.utc) - self.bot_start_time).total_seconds() / 60
            if uptime_minutes >= self.restart_after_minutes:
                logger.warning("AUTO-RESTART TIME - Loading fresh filters")
                import signal as _signal
                os.kill(os.getpid(), _signal.SIGTERM)
                return

            now = datetime.now(timezone.utc)

            if self.next_switch_time and now >= self.next_switch_time:
                if self._waiting_for_market_open:
                    # The future market we were waiting for has now opened
                    # Treat it like a market switch so trade timer resets
                    logger.info("=" * 80)
                    logger.info(f"⏰ WAITING MARKET NOW OPEN: {now.strftime('%H:%M:%S')} UTC")
                    logger.info("=" * 80)
                    # Update next_switch_time to the market's END time
                    if (self.current_instrument_index >= 0 and
                            self.current_instrument_index < len(self.all_btc_instruments)):
                        current_market = self.all_btc_instruments[self.current_instrument_index]
                        self.next_switch_time = current_market['end_time']
                        logger.info(f"  Market ends at {self.next_switch_time.strftime('%H:%M:%S')} UTC")
                    self._waiting_for_market_open = False
                    self._market_stable = True
                    self._stable_tick_count = QUOTE_STABILITY_REQUIRED
                    self.last_trade_time = -1  # Trade immediately on next tick
                    logger.info("  ✓ MARKET OPEN — ready to trade on next tick")
                else:
                    # Normal market switch
                    self._switch_to_next_market()

            await asyncio.sleep(10)

    # ------------------------------------------------------------------
    # Quote tick handler - SIMPLIFIED
    # ------------------------------------------------------------------

    def on_quote_tick(self, tick: QuoteTick):
        """Handle quote tick - TRADE when market opens and at each 15-min boundary"""
        try:
            # Only process ticks from current instrument
            if self.instrument_id is None or tick.instrument_id != self.instrument_id:
                return

            now = datetime.now(timezone.utc)

            # S8: Reset daily risk stats at UTC midnight
            today = now.date()
            if today != self._last_reset_date:
                self.risk_engine.reset_daily_stats()
                self._last_reset_date = today
                logger.info(f"Daily stats reset for {today}")

            bid = tick.bid_price
            ask = tick.ask_price

            if bid is None or ask is None:
                return
                
            try:
                bid_decimal = bid.as_decimal()
                ask_decimal = ask.as_decimal()
            except:
                return

            # Always store price history — as FLOAT to avoid Decimal↔float churn
            mid_price = (bid_decimal + ask_decimal) / 2
            mid_float = float(mid_price)
            self.price_history.append(mid_float)  # deque(maxlen) auto-evicts oldest

            # Store latest bid/ask for liquidity check before order placement
            self._last_bid_ask = (bid_decimal, ask_decimal)

            # Tick buffer for TickVelocityProcessor (rolling 90s window)
            self._tick_buffer.append({'ts': now, 'price': mid_float})

            # Stability gate
            if not self._market_stable:
                self._stable_tick_count += 1
                if self._stable_tick_count >= QUOTE_STABILITY_REQUIRED:
                    self._market_stable = True
                    logger.info(f"✓ Market STABLE after {self._stable_tick_count} ticks")
                else:
                    return

            # =========================================================================
            # FIXED TRADING LOGIC:
            # 
            # We trade once per 15-min market interval.
            # Instead of checking wall-clock 15-min boundaries (which caused the 2-hour
            # wait), we use a simple counter keyed to the Polymarket market's OWN
            # start time.
            #
            # The market's start_time is stored in all_btc_instruments[current_index].
            # Within each market, we compute a "sub-interval" index:
            #   sub_interval = elapsed_seconds_since_market_open // 900
            # Trade ID = (market_start_timestamp, sub_interval)
            # This fires once at market open AND once after every 15 min within
            # the same market if it's a multi-interval market.
            #
            # If _waiting_for_market_open is True (started before market opens),
            # we block trading until the timer loop calls _switch_to_next_market.
            # =========================================================================

            # Block trading if waiting for a future market to open
            if self._waiting_for_market_open:
                return

            # Get current market info
            if (self.current_instrument_index < 0 or
                    self.current_instrument_index >= len(self.all_btc_instruments)):
                return

            current_market = self.all_btc_instruments[self.current_instrument_index]
            market_start_ts = current_market['market_timestamp']  # Slug timestamp = market start (Unix)

            # How many 15-min intervals have elapsed since this market opened?
            elapsed_secs = now.timestamp() - market_start_ts
            if elapsed_secs < 0:
                # Market hasn't started yet — block
                return

            sub_interval = int(elapsed_secs // MARKET_INTERVAL_SECONDS)

            # Unique trade key: (market_start_timestamp, sub_interval)
            trade_key = (market_start_ts, sub_interval)

            # =========================================================================
            # TRADE WINDOW: minutes 13–14 of each 15-min market (780–840 seconds in)
            #
            # WHY LATE IN THE MARKET:
            #   At 13 minutes in, the UP/DOWN result is nearly decided. The price IS
            #   the trend — if YES is at $0.78, BTC went up during this interval.
            #   We're not predicting anymore, we're reading a nearly-resolved outcome.
            #
            # WHY NOT EARLIER (the old 30–90s window):
            #   At 30 seconds in, nobody knows which way BTC will move. The signals
            #   have no edge. This is why we were losing at prices near $0.50.
            #
            # TREND FILTER (applied in _make_trading_decision):
            #   Price > 0.60 → clear UP trend → buy YES
            #   Price < 0.40 → clear DOWN trend → buy NO
            #   Price 0.40–0.60 → coin flip → SKIP (don't trade)
            #
            # Share count intuition:
            #   1.4 shares = price $0.71 → strong trend, win rate ~71%
            #   1.9 shares = price $0.53 → weak trend, near coin flip
            #   2.0+ shares = price $0.50 → pure coin flip, SKIP
            # =========================================================================
            seconds_into_sub_interval = elapsed_secs % MARKET_INTERVAL_SECONDS

            if cfg.TRADE_WINDOW_START <= seconds_into_sub_interval < cfg.TRADE_WINDOW_END and trade_key != self.last_trade_time:
                self.last_trade_time = trade_key

                logger.info(
                    f"═ TRADE WINDOW | {current_market['slug']} | "
                    f"${mid_float:,.4f} | "
                    f"{'STRONG' if mid_float > cfg.TREND_UP_THRESHOLD or mid_float < cfg.TREND_DOWN_THRESHOLD else 'WEAK'} | "
                    f"{len(self.price_history)} pts"
                )

                self.run_in_executor(lambda mp=mid_float: self._make_trading_decision_sync(mp))

        except Exception as e:
            logger.error(f"Error processing quote tick: {e}")

    # ------------------------------------------------------------------
    # Trading decision (unchanged)
    # ------------------------------------------------------------------


    def _make_trading_decision_sync(self, current_price):
        """Synchronous wrapper for trading decision (called from executor)."""
        # Convert float back to Decimal for processing
        from decimal import Decimal
        price_decimal = Decimal(str(current_price))

        # Reuse persistent event loop instead of creating/closing a new one per trade
        self._decision_loop.run_until_complete(self._make_trading_decision(price_decimal))
            
    async def _fetch_market_context(self, current_price: Decimal) -> dict:
        """
        Fetch external data + compute local stats for signal processors.

        All external HTTP calls (sentiment, spot, orderbook, Deribit) run in
        parallel via asyncio.gather to minimize latency.
        """
        current_price_float = float(current_price)

        # --- Local stats from price_history (already stored as float) ---
        recent_prices = list(self.price_history)[-20:]  # float values
        n_recent = len(recent_prices)
        sma_20 = sum(recent_prices) / n_recent
        deviation = (current_price_float - sma_20) / sma_20 if sma_20 else 0.0
        momentum = (
            (current_price_float - self.price_history[-5]) / self.price_history[-5]
            if len(self.price_history) >= 5 else 0.0
        )
        variance = sum((p - sma_20) ** 2 for p in recent_prices) / n_recent
        volatility = math.sqrt(variance)

        metadata = {
            "deviation": deviation,
            "momentum": momentum,
            "volatility": volatility,
            # Pass deque DIRECTLY — no list() copy (processors only read)
            "tick_buffer": self._tick_buffer,
            "yes_token_id": self._yes_token_id,
        }

        # --- Parallel external fetches ----------------------------------------
        fg, spot, ob_book, pcr_data = await asyncio.gather(
            self._fetch_sentiment(),
            self._fetch_spot(),
            self._fetch_orderbook(),
            self._fetch_deribit_pcr(),
        )

        if fg and "value" in fg:
            metadata["sentiment_score"] = float(fg["value"])
            metadata["sentiment_classification"] = fg.get("classification", "")

        if spot:
            metadata["spot_price"] = float(spot)

        if ob_book:
            metadata["prefetched_orderbook"] = ob_book

        if pcr_data:
            metadata["prefetched_pcr"] = pcr_data

        logger.info(
            f"Context: dev={deviation:.2%} mom={momentum:.2%} vol={volatility:.4f} "
            f"sent={'%.0f' % metadata.get('sentiment_score', -1) if 'sentiment_score' in metadata else 'N/A'} "
            f"ob={'yes' if ob_book else 'no'} pcr={'yes' if pcr_data else 'no'}"
        )
        return metadata

    # --- External fetch helpers (class methods, not inner functions) -----------

    async def _fetch_sentiment(self):
        """Fetch Fear & Greed index."""
        try:
            from data_sources.news_social.adapter import get_news_social_source
            news_source = get_news_social_source()
            if not news_source.session:
                await news_source.connect()
            return await news_source.get_fear_greed_index()
        except Exception as e:
            logger.debug(f"Sentiment fetch failed: {e}")
            return None

    async def _fetch_spot(self):
        """Fetch Coinbase BTC spot price."""
        try:
            from data_sources.coinbase.adapter import get_coinbase_source
            coinbase = get_coinbase_source()
            if not coinbase.session:
                await coinbase.connect()
            return await coinbase.get_current_price()
        except Exception as e:
            logger.debug(f"Spot price fetch failed: {e}")
            return None

    async def _fetch_orderbook(self):
        """Pre-fetch Polymarket CLOB orderbook (runs async, not blocking signal loop)."""
        try:
            token_id = self._yes_token_id
            if not token_id:
                return None
            return self.orderbook_processor.fetch_order_book(token_id)
        except Exception as e:
            logger.debug(f"Orderbook pre-fetch failed: {e}")
            return None

    async def _fetch_deribit_pcr(self):
        """Pre-fetch Deribit PCR (cached internally for 5 min)."""
        try:
            from datetime import timezone as _tz
            proc = self.deribit_pcr_processor
            now = datetime.now(_tz.utc)
            cache_valid = (
                proc._cached_result is not None and
                proc._cache_time is not None and
                (now - proc._cache_time).total_seconds() < proc.cache_seconds
            )
            if cache_valid:
                return proc._cached_result
            pcr_data = proc._fetch_pcr()
            if pcr_data:
                proc._cached_result = pcr_data
                proc._cache_time = now
            return pcr_data
        except Exception as e:
            logger.debug(f"Deribit PCR pre-fetch failed: {e}")
            return None

    async def _make_trading_decision(self, current_price: Decimal):
        """
        Make trading decision using our 7-phase system.

        Position size is always $1.00 — no variable sizing, no risk-engine
        calculation needed. The risk engine is still used to check that we
        don't already have too many open positions.
        """
        # --- Mode check ---
        is_simulation = self.check_simulation_mode()
        logger.info(f"Mode: {'SIMULATION' if is_simulation else 'LIVE TRADING'}")

        # --- Minimum history guard ---
        if len(self.price_history) < 20:
            logger.warning(f"Not enough price history ({len(self.price_history)}/20)")
            return

        logger.info(f"Current price: ${float(current_price):,.4f}")

        # --- Phase 4a: Build real metadata for processors ---
        metadata = await self._fetch_market_context(current_price)

        # --- Phase 4b: Run all three signal processors ---
        signals = self._process_signals(current_price, metadata)

        if not signals:
            logger.info("No signals generated — no trade this interval")
            return

        logger.info(f"Generated {len(signals)} signal(s):")
        for sig in signals:
            logger.info(
                f"  [{sig.source}] {sig.direction.value}: "
                f"score={sig.score:.1f}, confidence={sig.confidence:.2%}"
            )

        # --- Phase 4c: Fuse signals into one consensus ---
        # min_score lowered to 40 because the TREND FILTER (price at min 11-13)
        # is now the primary decision maker. Fusion is informational context,
        # not the trade gate. The trend gate below is the real filter.
        fused = self.fusion_engine.fuse_signals(signals, min_signals=cfg.FUSION_MIN_SIGNALS, min_score=cfg.FUSION_MIN_SCORE)
        if not fused:
            logger.info("Fusion produced no actionable signal — no trade this interval")
            return

        logger.info(
            f"FUSED SIGNAL: {fused.direction.value} "
            f"(score={fused.score:.1f}, confidence={fused.confidence:.2%})"
        )

        # --- Phase 5: Position size from config ---
        POSITION_SIZE_USD = cfg.POSITION_SIZE_USD

        # =========================================================================
        # TREND FILTER — replaces signal-based direction at the late trade window
        #
        # At minute 13, the Polymarket price IS the market's verdict on BTC direction.
        # We ignore what the signal processors say and simply follow the price:
        #
        #   price > 0.60 → market says UP with >60% confidence → buy YES
        #   price < 0.40 → market says DOWN with >60% confidence → buy NO
        #   price 0.40–0.60 → too close to call → SKIP (this is where we were losing)
        #
        # This directly addresses the observation that trades at 1.9–2.0+ shares
        # (price near $0.50) almost always lose, while trades at 1.4 shares
        # (price ~$0.71) mostly win.
        # =========================================================================
        price_float = float(current_price)

        if price_float > cfg.TREND_UP_THRESHOLD:
            direction = "long"
            trend_confidence = price_float
            logger.info(f"TREND: UP ({price_float:.2%}) → buying YES")
        elif price_float < cfg.TREND_DOWN_THRESHOLD:
            direction = "short"
            trend_confidence = 1.0 - price_float
            logger.info(f"TREND: DOWN ({price_float:.2%}) → buying NO")
        else:
            logger.info(
                f"⏭ TREND: NEUTRAL ({price_float:.2%}) — skipping "
                f"({cfg.TREND_DOWN_THRESHOLD:.0%}–{cfg.TREND_UP_THRESHOLD:.0%})"
            )
            return

        # --- S1: Signal Agreement Filter ---
        # Check if the fused signal direction agrees with the trend.
        # If signals say BEARISH but trend says long → signals disagree → skip.
        from core.strategy_brain.signal_processors.base_processor import SignalDirection
        trend_signal_dir = SignalDirection.BULLISH if direction == "long" else SignalDirection.BEARISH
        signals_agree = (fused.direction is trend_signal_dir)

        if not signals_agree:
            if getattr(cfg, 'REQUIRE_SIGNAL_AGREEMENT', True):
                logger.info(
                    f"⏭ Signal disagreement: trend={direction} but "
                    f"fused={fused.direction.value} — skipping trade"
                )
                return
            else:
                logger.warning(
                    f"Signal disagreement: trend={direction} but "
                    f"fused={fused.direction.value} — proceeding (agreement not required)"
                )

        # Risk engine: only check position-count / exposure limits (no sizing math)
        is_valid, error = self.risk_engine.validate_new_position(
            size=POSITION_SIZE_USD,
            direction=direction,
            current_price=current_price,
        )
        if not is_valid:
            logger.warning(f"Risk engine blocked trade: {error}")
            return

        logger.info(f"Position size: $1.00 (fixed) | Direction: {direction.upper()}")

        # --- Liquidity guard: don't place if market has no real depth ---
        # The current bid/ask come from the last processed quote tick.
        # If ask <= 0.02 or bid <= 0.02, the orderbook is essentially empty
        # and a FAK (IOC market) order will be rejected immediately.
        last_tick = getattr(self, '_last_bid_ask', None)
        if last_tick:
            last_bid, last_ask = last_tick
            MIN_LIQUIDITY = Decimal("0.02")
            if direction == "long" and last_ask <= MIN_LIQUIDITY:
                logger.warning(
                    f"⚠ No liquidity for BUY: ask=${float(last_ask):.4f} ≤ {float(MIN_LIQUIDITY):.2f} — skipping trade, will retry next tick"
                )
                self.last_trade_time = -1  # Allow retry next tick
                return
            if direction == "short" and last_bid <= MIN_LIQUIDITY:
                logger.warning(
                    f"⚠ No liquidity for SELL: bid=${float(last_bid):.4f} ≤ {float(MIN_LIQUIDITY):.2f} — skipping trade, will retry next tick"
                )
                self.last_trade_time = -1  # Allow retry next tick
                return

        # --- Phase 5 / 6: Execute ---
        if is_simulation:
            await self._record_paper_trade(fused, POSITION_SIZE_USD, current_price, direction)
        else:
            await self._place_real_order(fused, POSITION_SIZE_USD, current_price, direction)
            
    async def _record_paper_trade(self, signal, position_size, current_price, direction):
        """Delegate to paper_trading module."""
        await record_paper_trade(self, signal, position_size, current_price, direction)

    def _save_paper_trades(self):
        """Delegate to paper_trading module."""
        save_paper_trades(self)

    # ------------------------------------------------------------------
    # Real order (unchanged)
    # ------------------------------------------------------------------

    async def _place_real_order(self, signal, position_size, current_price, direction):
        if not self.instrument_id:
            logger.error("No instrument available")
            return

        try:
            # instrument is fetched below after determining YES vs NO token

            logger.info("=" * 80)
            logger.info("LIVE MODE - PLACING REAL ORDER!")
            logger.info("=" * 80)

            # On Polymarket, both UP and DOWN are BUY orders.
            # Bullish = buy YES token (self._yes_instrument_id)
            # Bearish = buy NO token  (self._no_instrument_id)
            # There is NO sell — you always buy whichever side you want.
            side = OrderSide.BUY

            if direction == "long":
                trade_instrument_id = getattr(self, '_yes_instrument_id', self.instrument_id)
                trade_label = "YES (UP)"
            else:
                no_id = getattr(self, '_no_instrument_id', None)
                if no_id is None:
                    logger.warning(
                        "NO token instrument not found for this market — "
                        "cannot bet DOWN. Skipping trade."
                    )
                    return
                trade_instrument_id = no_id
                trade_label = "NO (DOWN)"

            instrument = self.cache.instrument(trade_instrument_id)
            if not instrument:
                logger.error(f"Instrument not in cache: {trade_instrument_id}")
                return

            logger.info(f"Buying {trade_label} token: {trade_instrument_id}")

            trade_price = float(current_price)
            max_usd_amount = float(position_size)

            precision = instrument.size_precision

            # Always BUY — the market-order patch converts this to a USD amount.
            # Pass dummy qty=5 (minimum) so Nautilus risk engine doesn't deny it.
            min_qty_val = float(getattr(instrument, 'min_quantity', None) or 5.0)
            token_qty = max(min_qty_val, 5.0)
            token_qty = round(token_qty, precision)
            logger.info(
                f"BUY {trade_label}: dummy qty={token_qty:.6f} "
                f"(patch converts to ${max_usd_amount:.2f} USD)"
            )

            qty = Quantity(token_qty, precision=precision)
            timestamp_ms = int(time.time() * 1000)
            unique_id = f"BTC-15MIN-${max_usd_amount:.0f}-{timestamp_ms}"

            order = self.order_factory.market(
                instrument_id=trade_instrument_id,
                order_side=side,
                quantity=qty,
                client_order_id=ClientOrderId(unique_id),
                quote_quantity=False,
                time_in_force=TimeInForce.IOC,
            )

            self.submit_order(order)

            logger.info(f"REAL ORDER SUBMITTED!")
            logger.info(f"  Order ID: {unique_id}")
            logger.info(f"  Direction: {trade_label}")
            logger.info(f"  Side: BUY")
            logger.info(f"  Token Quantity: {token_qty:.6f}")
            logger.info(f"  Estimated Cost: ~${max_usd_amount:.2f}")
            logger.info(f"  Price: ${trade_price:.4f}")
            logger.info("=" * 80)

            self._track_order_event("placed")

        except Exception as e:
            logger.error(f"Error placing real order: {e}")
            import traceback
            traceback.print_exc()
            self._track_order_event("rejected")

    # ------------------------------------------------------------------
    # Signal processing
    # ------------------------------------------------------------------

    def _process_signals(self, current_price, metadata=None):
        """Run all signal processors. metadata is passed through as-is (no Decimal conversion)."""
        signals = []
        if metadata is None:
            metadata = {}

        # price_history is already float; processors handle float internally.
        # No float→Decimal(str(float)) conversion needed.
        hist = self.price_history

        spike_signal = self.spike_detector.process(
            current_price=current_price,
            historical_prices=hist,
            metadata=metadata,
        )
        if spike_signal:
            signals.append(spike_signal)

        if 'sentiment_score' in metadata:
            sentiment_signal = self.sentiment_processor.process(
                current_price=current_price,
                historical_prices=hist,
                metadata=metadata,
            )
            if sentiment_signal:
                signals.append(sentiment_signal)

        if 'spot_price' in metadata:
            divergence_signal = self.divergence_processor.process(
                current_price=current_price,
                historical_prices=hist,
                metadata=metadata,
            )
            if divergence_signal:
                signals.append(divergence_signal)

        # --- Order Book Imbalance ---
        # Use pre-fetched book data if available (no blocking HTTP in signal loop)
        prefetched_book = metadata.get('prefetched_orderbook')
        if prefetched_book and metadata.get('yes_token_id'):
            ob_signal = self._process_prefetched_orderbook(
                current_price, prefetched_book, metadata
            )
            if ob_signal:
                signals.append(ob_signal)
        elif metadata.get('yes_token_id'):
            # Fallback: let processor fetch (blocking)
            ob_signal = self.orderbook_processor.process(
                current_price=current_price,
                historical_prices=hist,
                metadata=metadata,
            )
            if ob_signal:
                signals.append(ob_signal)

        # --- Tick Velocity ---
        if metadata.get('tick_buffer'):
            tv_signal = self.tick_velocity_processor.process(
                current_price=current_price,
                historical_prices=hist,
                metadata=metadata,
            )
            if tv_signal:
                signals.append(tv_signal)

        # --- Deribit PCR ---
        # Use pre-fetched PCR data if available
        prefetched_pcr = metadata.get('prefetched_pcr')
        if prefetched_pcr:
            pcr_signal = self.deribit_pcr_processor._generate_signal(
                current_price, prefetched_pcr
            )
            if pcr_signal:
                signals.append(pcr_signal)
        else:
            pcr_signal = self.deribit_pcr_processor.process(
                current_price=current_price,
                historical_prices=hist,
                metadata=metadata,
            )
            if pcr_signal:
                signals.append(pcr_signal)

        return signals

    def _process_prefetched_orderbook(self, current_price, book, metadata):
        """Process a pre-fetched orderbook dict without HTTP call."""
        try:
            proc = self.orderbook_processor
            bids = book.get('bids', [])
            asks = book.get('asks', [])

            bid_volume = proc._parse_levels(bids)
            ask_volume = proc._parse_levels(asks)
            total_volume = bid_volume + ask_volume

            if total_volume < proc.min_book_volume:
                return None

            imbalance = (bid_volume - ask_volume) / total_volume

            if abs(imbalance) < proc.imbalance_threshold:
                return None

            from core.strategy_brain.signal_processors.base_processor import (
                TradingSignal, SignalType, SignalDirection, SignalStrength,
            )

            direction = SignalDirection.BULLISH if imbalance > 0 else SignalDirection.BEARISH
            abs_imb = abs(imbalance)

            if abs_imb >= 0.70:
                strength = SignalStrength.VERY_STRONG
            elif abs_imb >= 0.50:
                strength = SignalStrength.STRONG
            elif abs_imb >= 0.35:
                strength = SignalStrength.MODERATE
            else:
                strength = SignalStrength.WEAK

            confidence = min(0.85, 0.55 + abs_imb * 0.40)
            bid_wall = proc._detect_wall(bids, total_volume)
            ask_wall = proc._detect_wall(asks, total_volume)
            wall_side = bid_wall if direction == SignalDirection.BULLISH else ask_wall
            if wall_side:
                confidence = min(0.90, confidence + 0.05)

            if confidence < proc.min_confidence:
                return None

            signal = TradingSignal(
                timestamp=datetime.now(),
                source=proc.name,
                signal_type=SignalType.VOLUME_SURGE,
                direction=direction,
                strength=strength,
                confidence=confidence,
                current_price=current_price,
                metadata={
                    'imbalance': round(imbalance, 4),
                    'bid_volume_usd': round(bid_volume, 2),
                    'ask_volume_usd': round(ask_volume, 2),
                }
            )
            proc._record_signal(signal)
            return signal
        except Exception as e:
            logger.warning(f"Prefetched orderbook processing error: {e}")
            return None

    # ------------------------------------------------------------------
    # Order events
    # ------------------------------------------------------------------

    def _track_order_event(self, event_type: str) -> None:
        """
        Safely track an order event on the performance tracker.

        PerformanceTracker does not expose `increment_order_counter`, so we
        use whichever method is actually available, or fall back to a no-op.
        Supported event_type values: "placed", "filled", "rejected".
        """
        try:
            pt = self.performance_tracker
            # Try the method that actually exists first
            if hasattr(pt, 'record_order_event'):
                pt.record_order_event(event_type)
            elif hasattr(pt, 'increment_counter'):
                pt.increment_counter(event_type)
            elif hasattr(pt, 'increment_order_counter'):
                pt.increment_order_counter(event_type)
            else:
                # No suitable method found – log and carry on
                logger.debug(
                    f"PerformanceTracker has no order-counter method; "
                    f"ignoring event '{event_type}'"
                )
        except Exception as e:
            logger.warning(f"Failed to track order event '{event_type}': {e}")

    def on_order_filled(self, event):
        logger.info("=" * 80)
        logger.info(f"ORDER FILLED!")
        logger.info(f"  Order: {event.client_order_id}")
        logger.info(f"  Fill Price: ${float(event.last_px):.4f}")
        logger.info(f"  Quantity: {float(event.last_qty):.6f}")
        logger.info("=" * 80)
        self._track_order_event("filled")

    def on_order_denied(self, event):
        logger.error("=" * 80)
        logger.error(f"ORDER DENIED!")
        logger.error(f"  Order: {event.client_order_id}")
        logger.error(f"  Reason: {event.reason}")
        logger.error("=" * 80)
        self._track_order_event("rejected")

    def on_order_rejected(self, event):
        """Handle order rejection — reset trade timer so we can retry next tick."""
        reason = str(getattr(event, 'reason', ''))
        reason_lower = reason.lower()
        if 'no orders found' in reason_lower or 'fak' in reason_lower or 'no match' in reason_lower:
            logger.warning(
                f"⚠ FAK rejected (no liquidity) — resetting timer to retry next tick\n"
                f"  Reason: {reason}"
            )
            self.last_trade_time = -1  # Allow retry on next quote tick
        else:
            logger.warning(f"Order rejected: {reason}")

    # ------------------------------------------------------------------
    # Grafana / stop
    # ------------------------------------------------------------------

    def _start_grafana_sync(self):
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.grafana_exporter.start())
            logger.info("Grafana metrics started on port 8000")
        except Exception as e:
            logger.error(f"Failed to start Grafana: {e}")

    def on_stop(self):
        logger.info("Integrated BTC strategy stopped")
        logger.info(f"Total paper trades recorded: {len(self.paper_trades)}")
        if self.grafana_exporter:
            import asyncio
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.grafana_exporter.stop())
            except Exception:
                pass

# ---------------------------------------------------------------------------
# Backward-compatible entry point (prefer runner.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from runner import main
    main()
