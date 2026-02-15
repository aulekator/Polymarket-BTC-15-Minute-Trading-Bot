"""
Custom Data Provider for NautilusTrader
Bridges our ingestion layer to Nautilus data engine
"""
import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from collections import defaultdict

from nautilus_trader.model.data import QuoteTick, TradeTick, Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId, TradeId
from nautilus_trader.model.enums import AggressorSide, BarAggregation, PriceType
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.common.component import LiveClock, Logger
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.data.engine import DataEngine
from loguru import logger as loguru_logger
import os

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.ingestion.adapters.unified_adapter import UnifiedDataAdapter, MarketData
from core.nautilus_core.instruments.btc_instruments import get_instrument_registry


class CustomDataProvider:
    """
    Custom data provider that feeds market data from our ingestion layer
    into NautilusTrader's data engine.
    
    Converts:
    - MarketData → QuoteTick
    - MarketData → TradeTick (synthetic)
    - Aggregates → Bar data
    """
    
    def __init__(
        self,
        data_engine: DataEngine,
        clock: LiveClock,
        logger: Logger,
    ):
        """
        Initialize custom data provider.
        
        Args:
            data_engine: Nautilus data engine
            clock: Nautilus clock
            logger: Nautilus logger
        """
        self.data_engine = data_engine
        self.clock = clock
        self.logger = logger
        
        # Our unified adapter
        self.adapter: Optional[UnifiedDataAdapter] = None
        
        # Instrument registry
        self.instruments = get_instrument_registry()
        
        # Track last prices for each source
        self._last_prices: dict = {}
        
        # Bar aggregators (for creating candlesticks)
        self._bar_aggregators: dict = defaultdict(list)
        
        loguru_logger.info("Initialized Custom Data Provider")
    
    async def connect(self) -> None:
        """Connect to data sources."""
        loguru_logger.info("Connecting custom data provider...")
        
        # Create and connect unified adapter
        self.adapter = UnifiedDataAdapter()
        
        # Set callbacks
        self.adapter.on_price_update = self._on_price_update
        self.adapter.on_sentiment_update = self._on_sentiment_update
        
        # Connect all sources
        results = await self.adapter.connect_all()
        
        connected = sum(results.values())
        loguru_logger.info(f"Connected {connected}/{len(results)} data sources")
        
        # Register instruments with data engine
        self._register_instruments()
        
        # Start streaming
        await self.adapter.start_streaming()
        
        loguru_logger.info("Custom data provider connected and streaming")
    
    async def disconnect(self) -> None:
        """Disconnect from data sources."""
        if self.adapter:
            await self.adapter.disconnect_all()
        
        loguru_logger.info("Custom data provider disconnected")
    
    def _register_instruments(self) -> None:
        """Register instruments with data engine."""
        for instrument in self.instruments.get_all():
            # Add instrument to data engine's cache
            # This makes it available to strategies
            loguru_logger.info(f"Registered instrument: {instrument.id}")
    
    async def _on_price_update(self, data: MarketData) -> None:
        """
        Handle price update from ingestion layer.
        
        Converts to Nautilus QuoteTick and sends to data engine.
        
        Args:
            data: Market data from ingestion layer
        """
        try:
            # Map source to instrument
            instrument_id = self._get_instrument_id(data.source)
            if not instrument_id:
                return
            
            # Create quote tick
            quote_tick = self._create_quote_tick(data, instrument_id)
            
            if quote_tick:
                # Send to data engine
                self.data_engine.process(quote_tick)
                
                # Also create synthetic trade tick
                trade_tick = self._create_trade_tick(data, instrument_id)
                if trade_tick:
                    self.data_engine.process(trade_tick)
            
            # Update last price
            self._last_prices[data.source] = data.price
            
        except Exception as e:
            loguru_logger.error(f"Error processing price update: {e}")
    
    async def _on_sentiment_update(self, data) -> None:
        """
        Handle sentiment update.
        
        Args:
            data: Sentiment data
        """
        # Store sentiment for strategies to access
        loguru_logger.debug(f"Sentiment update: {data.score}/100 - {data.classification}")
    
    def _get_instrument_id(self, source: str) -> Optional[InstrumentId]:
        """
        Map data source to instrument ID.
        
        Args:
            source: Data source name
            
        Returns:
            InstrumentId or None
        """
        mapping = {
            "coinbase": "BTC-USD.COINBASE",
            "binance": "BTCUSDT.BINANCE",
        }
        
        instrument_id_str = mapping.get(source)
        if not instrument_id_str:
            return None
        
        instrument = self.instruments.get(instrument_id_str)
        return instrument.id if instrument else None
    
    def _create_quote_tick(
        self,
        data: MarketData,
        instrument_id: InstrumentId,
    ) -> Optional[QuoteTick]:
        """
        Create QuoteTick from market data.
        
        Args:
            data: Market data
            instrument_id: Instrument ID
            
        Returns:
            QuoteTick or None
        """
        try:
            # Use bid/ask if available, otherwise use price ± small spread
            if data.bid and data.ask:
                # Round to max 9 decimal places (Nautilus limit)
                bid_str = f"{float(data.bid):.9f}".rstrip('0').rstrip('.')
                ask_str = f"{float(data.ask):.9f}".rstrip('0').rstrip('.')
                bid_price = Price.from_str(bid_str if '.' in bid_str else f"{bid_str}.0")
                ask_price = Price.from_str(ask_str if '.' in ask_str else f"{ask_str}.0")
            else:
                # Create synthetic bid/ask with 0.1% spread
                spread = data.price * Decimal("0.001")
                bid_val = float(data.price - spread)
                ask_val = float(data.price + spread)
                # Round to max 9 decimal places
                bid_str = f"{bid_val:.9f}".rstrip('0').rstrip('.')
                ask_str = f"{ask_val:.9f}".rstrip('0').rstrip('.')
                bid_price = Price.from_str(bid_str if '.' in bid_str else f"{bid_str}.0")
                ask_price = Price.from_str(ask_str if '.' in ask_str else f"{ask_str}.0")
            
            # Default size
            bid_size = Quantity.from_str("1.0")
            ask_size = Quantity.from_str("1.0")
            
            # Create quote tick
            quote_tick = QuoteTick(
                instrument_id=instrument_id,
                bid_price=bid_price,
                ask_price=ask_price,
                bid_size=bid_size,
                ask_size=ask_size,
                ts_event=self._to_nanoseconds(data.timestamp),
                ts_init=self.clock.timestamp_ns(),
            )
            
            return quote_tick
            
        except Exception as e:
            loguru_logger.error(f"Error creating quote tick: {e}")
            return None
    
    def _create_trade_tick(
        self,
        data: MarketData,
        instrument_id: InstrumentId,
    ) -> Optional[TradeTick]:
        """
        Create synthetic TradeTick from market data.
        
        Args:
            data: Market data
            instrument_id: Instrument ID
            
        Returns:
            TradeTick or None
        """
        try:
            # Check if price changed (only create trade tick if price moved)
            last_price = self._last_prices.get(data.source)
            if last_price and last_price == data.price:
                return None  # No price change, skip trade tick
            
            # Determine aggressor side based on price movement
            if last_price:
                aggressor_side = (
                    AggressorSide.BUYER if data.price > last_price
                    else AggressorSide.SELLER
                )
            else:
                aggressor_side = AggressorSide.BUYER
            
            trade_tick = TradeTick(
                instrument_id=instrument_id,
                price=Price.from_str(str(data.price)),
                size=Quantity.from_str("1.0"),  # Synthetic size
                aggressor_side=aggressor_side,
                trade_id=TradeId(f"{data.source}_{data.timestamp.timestamp()}"),
                ts_event=self._to_nanoseconds(data.timestamp),
                ts_init=self.clock.timestamp_ns(),
            )
            
            return trade_tick
            
        except Exception as e:
            loguru_logger.error(f"Error creating trade tick: {e}")
            return None
    
    @staticmethod
    def _to_nanoseconds(dt: datetime) -> int:
        """Convert datetime to nanoseconds since epoch."""
        return int(dt.timestamp() * 1_000_000_000)
    
    def get_latest_price(self, source: str) -> Optional[Decimal]:
        """Get latest price from a source."""
        return self._last_prices.get(source)
    
    def get_price_consensus(self) -> Optional[dict]:
        """Get price consensus across all sources."""
        if self.adapter:
            return self.adapter.get_price_consensus()
        return None