"""
BTC Instrument Definitions for NautilusTrader
"""
from decimal import Decimal
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import CryptoPerpetual
from nautilus_trader.model.objects import Price, Quantity, Money
from nautilus_trader.model.currencies import USDC, BTC
from loguru import logger


def create_btc_polymarket_instrument() -> CryptoPerpetual:
    """
    Create BTC prediction market instrument for Polymarket.
    
    This represents the BTC price prediction market on Polymarket.
    We model it as a perpetual contract for compatibility with Nautilus.
    
    Returns:
        CryptoPerpetual instrument
    """
    instrument = CryptoPerpetual(
        instrument_id=InstrumentId(
            symbol=Symbol("BTC-POLYMARKET"),
            venue=Venue("POLYMARKET")
        ),
        raw_symbol=Symbol("BTC-POLYMARKET"),
        base_currency=BTC,
        quote_currency=USDC,
        settlement_currency=USDC,
        is_inverse=False,
        price_precision=2,  # $0.01 precision
        size_precision=4,   # 0.0001 precision
        price_increment=Price.from_str("0.01"),
        size_increment=Quantity.from_str("0.0001"),
        max_quantity=Quantity.from_str("1000000"),
        min_quantity=Quantity.from_str("0.01"),
        max_price=Price.from_str("1.00"),  # Prediction markets trade 0-1
        min_price=Price.from_str("0.00"),
        margin_init=Decimal("0.05"),  # 5% initial margin
        margin_maint=Decimal("0.03"),  # 3% maintenance margin
        maker_fee=Decimal("0.001"),  # 0.1% maker fee
        taker_fee=Decimal("0.002"),  # 0.2% taker fee
        ts_event=0,
        ts_init=0,
    )
    
    logger.info(f"Created Polymarket BTC instrument: {instrument.id}")
    return instrument


def create_btc_spot_instrument() -> CryptoPerpetual:
    """
    Create BTC spot price instrument (for reference data).
    
    This represents actual BTC-USD spot price from exchanges.
    Used for comparison and signal generation.
    
    Returns:
        CryptoPerpetual instrument
    """
    instrument = CryptoPerpetual(
        instrument_id=InstrumentId(
            symbol=Symbol("BTC-USD"),
            venue=Venue("COINBASE")
        ),
        raw_symbol=Symbol("BTC-USD"),
        base_currency=BTC,
        quote_currency=USDC,
        settlement_currency=USDC,
        is_inverse=False,
        price_precision=2,
        size_precision=8,
        price_increment=Price.from_str("0.01"),
        size_increment=Quantity.from_str("0.00000001"),
        max_quantity=Quantity.from_str("1000"),
        min_quantity=Quantity.from_str("0.001"),
        max_price=Price.from_str("1000000.00"),
        min_price=Price.from_str("1.00"),
        margin_init=Decimal("0.05"),
        margin_maint=Decimal("0.03"),
        maker_fee=Decimal("0.005"),  # 0.5%
        taker_fee=Decimal("0.005"),
        ts_event=0,
        ts_init=0,
    )
    
    logger.info(f"Created Coinbase BTC spot instrument: {instrument.id}")
    return instrument


def create_btc_binance_instrument() -> CryptoPerpetual:
    """
    Create Binance BTC instrument.
    
    Returns:
        CryptoPerpetual instrument
    """
    instrument = CryptoPerpetual(
        instrument_id=InstrumentId(
            symbol=Symbol("BTCUSDT"),
            venue=Venue("BINANCE")
        ),
        raw_symbol=Symbol("BTCUSDT"),
        base_currency=BTC,
        quote_currency=USDC,
        settlement_currency=USDC,
        is_inverse=False,
        price_precision=2,
        size_precision=8,
        price_increment=Price.from_str("0.01"),
        size_increment=Quantity.from_str("0.00000001"),
        max_quantity=Quantity.from_str("9000"),
        min_quantity=Quantity.from_str("0.00001"),
        max_price=Price.from_str("1000000.00"),
        min_price=Price.from_str("1.00"),
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
        maker_fee=Decimal("0.001"),
        taker_fee=Decimal("0.001"),
        ts_event=0,
        ts_init=0,
    )
    
    logger.info(f"Created Binance BTCUSDT instrument: {instrument.id}")
    return instrument


class InstrumentRegistry:
    """Registry for all trading instruments."""
    
    def __init__(self):
        """Initialize instrument registry."""
        self.instruments = {}
        self._setup_instruments()
        
        logger.info(f"Initialized instrument registry with {len(self.instruments)} instruments")
    
    def _setup_instruments(self) -> None:
        """Setup all instruments."""
        # Polymarket prediction market
        polymarket = create_btc_polymarket_instrument()
        self.instruments[str(polymarket.id)] = polymarket
        
        # Spot reference instruments
        coinbase = create_btc_spot_instrument()
        self.instruments[str(coinbase.id)] = coinbase
        
        binance = create_btc_binance_instrument()
        self.instruments[str(binance.id)] = binance
    
    def get(self, instrument_id: str) -> CryptoPerpetual:
        """Get instrument by ID."""
        return self.instruments.get(instrument_id)
    
    def get_polymarket(self) -> CryptoPerpetual:
        """Get Polymarket BTC instrument."""
        return self.get("BTC-POLYMARKET.POLYMARKET")
    
    def get_coinbase(self) -> CryptoPerpetual:
        """Get Coinbase BTC instrument."""
        return self.get("BTC-USD.COINBASE")
    
    def get_binance(self) -> CryptoPerpetual:
        """Get Binance BTC instrument."""
        return self.get("BTCUSDT.BINANCE")
    
    def get_all(self) -> list:
        """Get all instruments."""
        return list(self.instruments.values())


# Singleton instance
_registry_instance = None

def get_instrument_registry() -> InstrumentRegistry:
    """Get singleton instrument registry."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = InstrumentRegistry()
    return _registry_instance