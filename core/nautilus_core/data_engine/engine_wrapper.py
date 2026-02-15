"""
Nautilus Data Engine Wrapper
Simplifies interaction with NautilusTrader's data engine
"""
from typing import Optional
import sys
import os

# Make core imports work from this subfolder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from datetime import datetime

from nautilus_trader.config import DataEngineConfig
from nautilus_trader.data.engine import DataEngine
from nautilus_trader.common.component import LiveClock, Logger, MessageBus
from nautilus_trader.cache.cache import Cache
from nautilus_trader.model.identifiers import InstrumentId, TraderId

from loguru import logger as loguru_logger

from core.nautilus_core.instruments.btc_instruments import get_instrument_registry
from core.nautilus_core.providers.custom_data_provider import CustomDataProvider
from core.nautilus_core.event_dispatcher.dispatcher import get_event_dispatcher


class NautilusDataEngineWrapper:
    """
    Wrapper around NautilusTrader's DataEngine.
    
    Provides simplified interface for:
    - Initializing Nautilus components
    - Managing data subscriptions
    - Integrating our custom data provider
    """
    
    def __init__(self):
        """Initialize Nautilus data engine wrapper."""
        # Clock (used by engine / msgbus / provider)
        self.clock = LiveClock()
        
        # Logger – no clock kwarg
        self.logger = Logger("nautilus.data_engine.wrapper")
        
        self.msgbus = MessageBus(
            trader_id=TraderId("TRADER-001"),
            clock=self.clock,
        )
        
        # Cache – no logger parameter anymore
        self.cache = Cache(
            database=None,          # in-memory only
            # config=CacheConfig(...)  # optional
        )
        
        # Data engine config
        config = DataEngineConfig(
            time_bars_timestamp_on_close=False,
            validate_data_sequence=True,
        )
        
        # The actual data engine
        self.engine = DataEngine(
            msgbus=self.msgbus,
            cache=self.cache,
            clock=self.clock,
            config=config,
        )
        
        # Custom provider (created later in start())
        self.data_provider: Optional[CustomDataProvider] = None
        
        # Instruments & events
        self.instruments = get_instrument_registry()
        self.event_dispatcher = get_event_dispatcher()
        
        self._is_running = False
        
        loguru_logger.info("Initialized Nautilus Data Engine Wrapper")
    
    async def start(self) -> None:
        """Start the data engine and data provider."""
        if self._is_running:
            loguru_logger.warning("Data engine already running")
            return
        
        loguru_logger.info("Starting Nautilus data engine...")
        
        self.engine.start()
        
        self._register_instruments()
        
        self.data_provider = CustomDataProvider(
            data_engine=self.engine,
            clock=self.clock,
            logger=self.logger,
        )
        
        await self.data_provider.connect()
        
        self._is_running = True
        loguru_logger.info("Nautilus data engine started")
    
    async def stop(self) -> None:
        """Stop the data engine and data provider."""
        if not self._is_running:
            return
        
        loguru_logger.info("Stopping Nautilus data engine...")
        
        if self.data_provider:
            await self.data_provider.disconnect()
        
        self.engine.stop()
        
        self._is_running = False
        loguru_logger.info("Nautilus data engine stopped")
    
    def _register_instruments(self) -> None:
        """Register all instruments from registry with cache."""
        for instrument in self.instruments.get_all():
            self.cache.add_instrument(instrument)
            loguru_logger.info(f"Registered instrument in cache: {instrument.id}")
    
    def subscribe_quotes(self, instrument_id: InstrumentId) -> None:
        """Subscribe to quote ticks."""
        self.engine.subscribe_quote_ticks(instrument_id)
        loguru_logger.info(f"Subscribed to quotes for {instrument_id}")
    
    def subscribe_trades(self, instrument_id: InstrumentId) -> None:
        """Subscribe to trade ticks."""
        self.engine.subscribe_trade_ticks(instrument_id)
        loguru_logger.info(f"Subscribed to trades for {instrument_id}")
    
    def subscribe_bars(
        self,
        instrument_id: InstrumentId,
        bar_type: str,  # e.g. "15-MINUTE-LAST"
    ) -> None:
        """Subscribe to bar data (placeholder – implement when needed)."""
        loguru_logger.info(f"Subscribed to {bar_type} bars for {instrument_id}")
    
    def get_instrument(self, instrument_id: str) -> Optional[any]:
        return self.instruments.get(instrument_id)
    
    def get_latest_quote(self, instrument_id: InstrumentId) -> Optional[any]:
        return self.cache.quote(instrument_id)
    
    def get_latest_trade(self, instrument_id: InstrumentId) -> Optional[any]:
        return self.cache.trade(instrument_id)
    
    def get_price_consensus(self) -> Optional[dict]:
        if self.data_provider:
            return self.data_provider.get_price_consensus()
        return None
    
    def get_status(self) -> dict:
        return {
            "is_running": self._is_running,
            "instruments_registered": len(self.instruments.get_all()),
            "data_provider_connected": (
                self.data_provider is not None and
                self.data_provider.adapter is not None
            ),
        }


# Singleton
_engine_wrapper_instance = None

def get_nautilus_engine() -> NautilusDataEngineWrapper:
    global _engine_wrapper_instance
    if _engine_wrapper_instance is None:
        _engine_wrapper_instance = NautilusDataEngineWrapper()
    return _engine_wrapper_instance