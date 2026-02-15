import os
import asyncio
import math
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from loguru import logger
from dotenv import load_dotenv

from nautilus_trader.adapters.polymarket import POLYMARKET
from nautilus_trader.adapters.polymarket import (
    PolymarketDataClientConfig,
    PolymarketExecClientConfig,
)
from nautilus_trader.adapters.polymarket.factories import (
    PolymarketLiveDataClientFactory,
    PolymarketLiveExecClientFactory,
)
from nautilus_trader.config import (
    InstrumentProviderConfig,
    LiveDataEngineConfig,
    LiveExecEngineConfig,
    LiveRiskEngineConfig,
    LoggingConfig,
    TradingNodeConfig,
)
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.objects import Quantity, Price
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.trading.strategy import Strategy

load_dotenv()


def current_btc_15m_slug() -> str:
    """
    Get the current BTC 15-minute market slug.
    
    Polymarket BTC 15-min markets follow the pattern:
    btc-updown-15m-{unix_timestamp}
    
    Where unix_timestamp is the start of the 15-minute interval.
    
    Returns:
        Current market slug (e.g., "btc-updown-15m-1739461800")
    """
    now = datetime.now(timezone.utc)
    unix_s = int(now.timestamp())
    interval_start = math.floor(unix_s / 900) * 900  # 900 = 15×60
    slug = f"btc-updown-15m-{interval_start}"
    
    logger.info(f"Current BTC 15-min market slug: {slug}")
    return slug


def get_next_btc_15m_markets(count: int = 3) -> list[str]:
    """
    Get the next N BTC 15-minute market slugs.
    
    Useful for pre-loading markets that will be active soon.
    
    Args:
        count: Number of future markets to include
        
    Returns:
        List of market slugs including current and future markets
    """
    now = datetime.now(timezone.utc)
    unix_s = int(now.timestamp())
    interval_start = math.floor(unix_s / 900) * 900
    
    slugs = []
    for i in range(count):
        timestamp = interval_start + (i * 900)
        slug = f"btc-updown-15m-{timestamp}"
        slugs.append(slug)
    
    logger.info(f"BTC 15-min market slugs (next {count}): {slugs}")
    return slugs


class PolymarketBTCIntegration:
    """
    Integration layer between BTC strategy and Polymarket via Nautilus.
    
    This handles:
    - Nautilus node setup
    - Polymarket client configuration
    - Instrument loading
    - Order routing
    - Position tracking
    """
    
    def __init__(
        self,
        simulation_mode: bool = True,
        btc_market_condition_id: Optional[str] = None,
    ):
        """
        Initialize Polymarket integration.
        
        Args:
            simulation_mode: If True, don't place real orders
            btc_market_condition_id: Polymarket condition ID for BTC market
        """
        self.simulation_mode = simulation_mode
        self.btc_market_condition_id = btc_market_condition_id
        
        # Nautilus components
        self.node: Optional[TradingNode] = None
        self.strategy: Optional[Strategy] = None
        
        # Track Polymarket instruments
        self.btc_instrument_id: Optional[InstrumentId] = None
        
        # Statistics
        self.orders_submitted = 0
        self.orders_filled = 0
        self.orders_rejected = 0
        
        mode = "SIMULATION" if simulation_mode else "LIVE TRADING"
        logger.info(f"Initialized Polymarket BTC Integration [{mode}]")
    
    async def start(self) -> bool:
        """
        Start the Nautilus trading node with Polymarket.
        
        Returns:
            True if started successfully
        """
        try:
            logger.info("="*80)
            logger.info("STARTING NAUTILUS-POLYMARKET INTEGRATION")
            logger.info("="*80)
            
            # Create Nautilus config
            config = self._create_nautilus_config()
            
            # Create trading node
            self.node = TradingNode(config=config)
            
            # Add Polymarket factories
            self.node.add_data_client_factory(POLYMARKET, PolymarketLiveDataClientFactory)
            self.node.add_exec_client_factory(POLYMARKET, PolymarketLiveExecClientFactory)
            
            # Build node
            logger.info("Building Nautilus node...")
            self.node.build()
            
            logger.info("✓ Nautilus node built successfully")
            
            # Start node asynchronously
            logger.info("Starting node (instruments loading)...")
            self.node.start()
            
            # Wait for instruments to load
            await asyncio.sleep(5)
            
            # Find BTC instrument
            await self._find_btc_instrument()
            
            logger.info("✓ Nautilus-Polymarket integration started")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start integration: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _create_nautilus_config(self) -> TradingNodeConfig:
        """Create Nautilus trading node configuration."""
        
        # Get current and next BTC 15-min market slugs
        btc_markets = get_next_btc_15m_markets(count=2)  # Current + next market
        
        # Instrument provider config - use Gamma Markets API for faster filtering
        instrument_cfg = InstrumentProviderConfig(
            load_all=False,  # Only load specific markets
            use_gamma_markets=True,  # CRITICAL: Use Gamma API for slug filtering
            filters={
                "active": True,
                "closed": False,
                "archived": False,
                "slug": btc_markets,  # Load current 15-min BTC market(s)
            }
        )
        
        logger.info(f"Loading BTC 15-min markets: {btc_markets}")
        
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
        
        # Trading node config
        node_config = TradingNodeConfig(
            environment="live",
            trader_id="BTC-15MIN-BOT-001",
            logging=LoggingConfig(
                log_level="INFO",
                log_directory="./logs/nautilus",
            ),
            data_engine=LiveDataEngineConfig(qsize=6000),
            exec_engine=LiveExecEngineConfig(qsize=6000),
            risk_engine=LiveRiskEngineConfig(
                bypass=self.simulation_mode,  # Bypass in simulation
            ),
            data_clients={POLYMARKET: poly_data_cfg},
            exec_clients={POLYMARKET: poly_exec_cfg},
        )
        
        return node_config
    
    async def _find_btc_instrument(self) -> bool:
        """
        Find the BTC 15-minute prediction market instrument.
        
        Returns:
            True if found
        """
        if not self.node:
            return False
        
        logger.info("Searching for BTC 15-min prediction market instruments...")
        
        # Get all instruments from cache
        instruments = self.node.cache.instruments()
        
        logger.info(f"Found {len(instruments)} total instruments")
        
        # Search for BTC 15-min instruments
        btc_instruments = []
        for instrument in instruments:
            instrument_str = str(instrument.id)
            if '.POLYMARKET' in instrument_str:
                # Log all Polymarket instruments for debugging
                logger.debug(f"  Polymarket instrument: {instrument.id}")
                
                # Check if it's a BTC market
                # Instruments follow pattern: {condition_id}-{token_id}.POLYMARKET
                # We loaded by slug, so any instrument here should be our BTC 15-min market
                btc_instruments.append(instrument)
                logger.info(f"  Found BTC 15-min instrument: {instrument.id}")
        
        if not btc_instruments:
            logger.error("No BTC 15-min instruments found!")
            logger.error("This usually means:")
            logger.error("  1. The current 15-min market hasn't been created yet")
            logger.error("  2. Credentials are incorrect")
            logger.error("  3. Gamma Markets API is not enabled")
            return False
        
        # Use the first BTC instrument (should be the current 15-min market)
        self.btc_instrument_id = btc_instruments[0].id
        logger.info(f"✓ Using BTC 15-min instrument: {self.btc_instrument_id}")
        
        # Log market details
        instrument = btc_instruments[0]
        logger.info(f"  Market details:")
        logger.info(f"    Price precision: {instrument.price_precision}")
        logger.info(f"    Size precision: {instrument.size_precision}")
        logger.info(f"    Min quantity: {instrument.min_quantity}")
        
        return True
    
    async def place_market_order(
        self,
        side: str,  # "buy" or "sell"
        size_usd: Decimal,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Place market order on Polymarket.
        
        Args:
            side: "buy" or "sell"
            size_usd: Size in USD
            metadata: Order metadata (signal info, etc.)
            
        Returns:
            Order ID if successful
        """
        if not self.node or not self.btc_instrument_id:
            logger.error("Integration not ready - node or instrument missing")
            return None
        
        if self.simulation_mode:
            logger.info(f"[SIMULATION] Would place {side.upper()} order for ${size_usd}")
            return f"sim_order_{datetime.now().timestamp()}"
        
        try:
            # Get instrument from cache
            instrument = self.node.cache.instrument(self.btc_instrument_id)
            
            if not instrument:
                logger.error(f"Instrument not in cache: {self.btc_instrument_id}")
                return None
            
            # Convert side
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            
            # Get current best price from market
            quote = self.node.cache.quote(self.btc_instrument_id)
            
            if not quote:
                logger.warning("No quote available, using mid price")
                current_price = Decimal("0.5")
            else:
                # Use mid price
                current_price = (quote.bid_price + quote.ask_price) / 2
            
            # Calculate token quantity
            # For Polymarket, tokens trade 0-1
            # To spend $X, you need X / price tokens
            if current_price > 0:
                token_qty = float(size_usd) / float(current_price)
            else:
                token_qty = float(size_usd) * 2  # Fallback
            
            # Round to instrument precision
            precision = instrument.size_precision
            token_qty = round(token_qty, precision)
            
            # Create quantity
            qty = Quantity(token_qty, precision=precision)
            
            # Generate unique order ID
            timestamp_ms = int(datetime.now().timestamp() * 1000)
            order_id = f"BTC-15MIN-{side.upper()}-{timestamp_ms}"
            
            # Create market order
            # CRITICAL: Use quote_quantity=False to specify quantity in TOKENS
            order = self.node.trader.order_factory.market(
                instrument_id=self.btc_instrument_id,
                order_side=order_side,
                quantity=qty,
                client_order_id=ClientOrderId(order_id),
                quote_quantity=False,  # TOKENS, not USD
                time_in_force=TimeInForce.IOC,  # Immediate or cancel
            )
            
            # Submit order
            logger.info(f"Submitting order: {order_side.name} {token_qty:.6f} tokens")
            logger.info(f"  Estimated cost: ${size_usd:.2f}")
            logger.info(f"  Price: ${float(current_price):.4f}")
            
            self.node.trader.submit_order(order)
            
            self.orders_submitted += 1
            
            logger.info(f"✓ Order submitted: {order_id}")
            
            return order_id
            
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            import traceback
            traceback.print_exc()
            self.orders_rejected += 1
            return None
    
    async def place_limit_order(
        self,
        side: str,
        size_usd: Decimal,
        limit_price: Decimal,  # 0-1 range
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Place limit order on Polymarket.
        
        Args:
            side: "buy" or "sell"
            size_usd: Size in USD
            limit_price: Limit price (0-1 range)
            metadata: Order metadata
            
        Returns:
            Order ID if successful
        """
        if not self.node or not self.btc_instrument_id:
            return None
        
        if self.simulation_mode:
            logger.info(f"[SIMULATION] Would place {side.upper()} limit @ ${limit_price:.4f}")
            return f"sim_order_{datetime.now().timestamp()}"
        
        try:
            instrument = self.node.cache.instrument(self.btc_instrument_id)
            
            if not instrument:
                return None
            
            # Convert side
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            
            # Calculate token quantity
            token_qty = float(size_usd) / float(limit_price) if limit_price > 0 else float(size_usd) * 2
            precision = instrument.size_precision
            token_qty = round(token_qty, precision)
            
            qty = Quantity(token_qty, precision=precision)
            
            # Format price
            price = Price.from_str(f"{float(limit_price):.4f}")
            
            # Generate order ID
            timestamp_ms = int(datetime.now().timestamp() * 1000)
            order_id = f"BTC-15MIN-LIMIT-{timestamp_ms}"
            
            # Create limit order
            order = self.node.trader.order_factory.limit(
                instrument_id=self.btc_instrument_id,
                order_side=order_side,
                quantity=qty,
                price=price,
                client_order_id=ClientOrderId(order_id),
                quote_quantity=False,  # Quantity in TOKENS
                time_in_force=TimeInForce.GTC,  # Good til cancelled
            )
            
            logger.info(f"Submitting limit order: {order_side.name} {token_qty:.6f} @ ${limit_price:.4f}")
            
            self.node.trader.submit_order(order)
            
            self.orders_submitted += 1
            
            logger.info(f"✓ Limit order submitted: {order_id}")
            
            return order_id
            
        except Exception as e:
            logger.error(f"Failed to place limit order: {e}")
            self.orders_rejected += 1
            return None
    
    def get_open_positions(self) -> list:
        """Get open positions from Nautilus."""
        if not self.node:
            return []
        
        return list(self.node.cache.positions_open())
    
    def get_balance(self) -> Dict[str, Any]:
        """Get account balance."""
        if not self.node:
            return {"USDC": 0.0}
        
        # Get account state from Nautilus cache
        account = self.node.cache.account(self.node.trader.id.get_tag())
        
        if not account:
            return {"USDC": 0.0}
        
        return {
            "USDC": float(account.balance_total().as_decimal()),
            "free": float(account.balance_free().as_decimal()),
            "locked": float(account.balance_locked().as_decimal()),
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get trading statistics."""
        return {
            "simulation_mode": self.simulation_mode,
            "orders_submitted": self.orders_submitted,
            "orders_filled": self.orders_filled,
            "orders_rejected": self.orders_rejected,
            "instrument_id": str(self.btc_instrument_id) if self.btc_instrument_id else None,
            "node_running": self.node is not None,
        }
    
    async def stop(self) -> None:
        """Stop the integration."""
        if self.node:
            logger.info("Stopping Nautilus node...")
            await self.node.stop_async()
            await self.node.dispose_async()
            self.node = None
        
        logger.info("Polymarket integration stopped")


# Singleton instance
_integration_instance: Optional[PolymarketBTCIntegration] = None

def get_polymarket_integration(
    simulation_mode: bool = True,
    btc_market_condition_id: Optional[str] = None,
) -> PolymarketBTCIntegration:
    """Get singleton Polymarket integration."""
    global _integration_instance
    
    if _integration_instance is None:
        _integration_instance = PolymarketBTCIntegration(
            simulation_mode=simulation_mode,
            btc_market_condition_id=btc_market_condition_id,
        )
    
    return _integration_instance