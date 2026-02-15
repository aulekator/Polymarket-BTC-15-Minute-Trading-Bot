"""
Binance WebSocket Data Source
Real-time BTC price streaming from Binance
"""
import asyncio
import json
from datetime import datetime
from decimal import Decimal
from typing import Optional, Callable, Dict, Any
import websockets
from loguru import logger


class BinanceWebSocketSource:
    """
    Binance WebSocket data source for real-time BTC data.
    
    Provides:
    - Real-time ticker updates
    - Trade stream
    - Order book updates
    - Kline (candlestick) data
    """
    
    def __init__(
        self,
        symbol: str = "btcusdt",
        ws_url: str = "wss://stream.binance.com:9443/ws",
    ):
        """
        Initialize Binance WebSocket source.
        
        Args:
            symbol: Trading pair (lowercase)
            ws_url: WebSocket endpoint URL
        """
        self.symbol = symbol.lower()
        self.ws_url = ws_url
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        
        # Callbacks
        self.on_price_update: Optional[Callable] = None
        self.on_trade: Optional[Callable] = None
        self.on_orderbook: Optional[Callable] = None
        
        # State
        self._is_running = False
        self._last_price: Optional[Decimal] = None
        self._last_update: Optional[datetime] = None
        
        logger.info(f"Initialized Binance WebSocket for {symbol.upper()}")
    
    async def connect(self, stream_type: str = "ticker") -> bool:
        """
        Connect to Binance WebSocket.
        
        Args:
            stream_type: "ticker", "trade", "depth", "kline_1m", etc.
            
        Returns:
            True if connected successfully
        """
        try:
            # Build stream URL
            stream = f"{self.symbol}@{stream_type}"
            url = f"{self.ws_url}/{stream}"
            
            self.websocket = await websockets.connect(url)
            self._is_running = True
            
            logger.info(f"✓ Connected to Binance WebSocket: {stream}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Binance WebSocket: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        self._is_running = False
        
        if self.websocket:
            await self.websocket.close()
            logger.info("Disconnected from Binance WebSocket")
    
    async def stream_ticker(self) -> None:
        """
        Stream 24hr ticker updates.
        
        Calls on_price_update callback with ticker data.
        """
        await self.connect("ticker")
        
        try:
            while self._is_running and self.websocket:
                message = await self.websocket.recv()
                data = json.loads(message)
                
                # Parse ticker data
                ticker = {
                    "timestamp": datetime.fromtimestamp(data["E"] / 1000),
                    "symbol": data["s"],
                    "price": Decimal(data["c"]),  # Current price
                    "open": Decimal(data["o"]),
                    "high": Decimal(data["h"]),
                    "low": Decimal(data["l"]),
                    "volume": Decimal(data["v"]),
                    "quote_volume": Decimal(data["q"]),
                    "price_change": Decimal(data["p"]),
                    "price_change_percent": Decimal(data["P"]),
                }
                
                self._last_price = ticker["price"]
                self._last_update = ticker["timestamp"]
                
                logger.debug(f"Binance BTC: ${ticker['price']:,.2f} ({ticker['price_change_percent']:+.2f}%)")
                
                # Call callback if registered
                if self.on_price_update:
                    await self.on_price_update(ticker)
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Binance WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error in Binance ticker stream: {e}")
        finally:
            await self.disconnect()
    
    async def stream_trades(self) -> None:
        """
        Stream individual trades.
        
        Calls on_trade callback with trade data.
        """
        await self.connect("trade")
        
        try:
            while self._is_running and self.websocket:
                message = await self.websocket.recv()
                data = json.loads(message)
                
                # Parse trade data
                trade = {
                    "timestamp": datetime.fromtimestamp(data["T"] / 1000),
                    "trade_id": data["t"],
                    "price": Decimal(data["p"]),
                    "quantity": Decimal(data["q"]),
                    "buyer_is_maker": data["m"],  # True if buyer is maker
                    "side": "sell" if data["m"] else "buy",
                }
                
                self._last_price = trade["price"]
                self._last_update = trade["timestamp"]
                
                logger.debug(f"Binance trade: {trade['side'].upper()} {trade['quantity']} @ ${trade['price']:,.2f}")
                
                # Call callback if registered
                if self.on_trade:
                    await self.on_trade(trade)
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Binance WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error in Binance trade stream: {e}")
        finally:
            await self.disconnect()
    
    async def stream_orderbook(self, depth: str = "5") -> None:
        """
        Stream order book depth updates.
        
        Args:
            depth: "5", "10", or "20" levels
            
        Calls on_orderbook callback with order book data.
        """
        await self.connect(f"depth{depth}")
        
        try:
            while self._is_running and self.websocket:
                message = await self.websocket.recv()
                data = json.loads(message)
                
                # Parse order book
                orderbook = {
                    "timestamp": datetime.now(),
                    "last_update_id": data.get("lastUpdateId"),
                    "bids": [
                        {"price": Decimal(b[0]), "quantity": Decimal(b[1])}
                        for b in data.get("bids", [])
                    ],
                    "asks": [
                        {"price": Decimal(a[0]), "quantity": Decimal(a[1])}
                        for a in data.get("asks", [])
                    ],
                }
                
                if orderbook["bids"]:
                    best_bid = orderbook["bids"][0]["price"]
                    best_ask = orderbook["asks"][0]["price"] if orderbook["asks"] else Decimal("0")
                    
                    logger.debug(f"Binance order book: Bid ${best_bid:,.2f} / Ask ${best_ask:,.2f}")
                
                # Call callback if registered
                if self.on_orderbook:
                    await self.on_orderbook(orderbook)
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Binance WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error in Binance orderbook stream: {e}")
        finally:
            await self.disconnect()
    
    async def stream_klines(self, interval: str = "1m") -> None:
        """
        Stream candlestick data.
        
        Args:
            interval: "1m", "5m", "15m", "1h", "4h", "1d", etc.
        """
        await self.connect(f"kline_{interval}")
        
        try:
            while self._is_running and self.websocket:
                message = await self.websocket.recv()
                data = json.loads(message)
                
                k = data["k"]  # Kline data
                
                candle = {
                    "timestamp": datetime.fromtimestamp(k["t"] / 1000),
                    "open": Decimal(k["o"]),
                    "high": Decimal(k["h"]),
                    "low": Decimal(k["l"]),
                    "close": Decimal(k["c"]),
                    "volume": Decimal(k["v"]),
                    "is_closed": k["x"],  # True if candle is closed
                }
                
                logger.debug(f"Binance kline ({interval}): O:{candle['open']} H:{candle['high']} L:{candle['low']} C:{candle['close']}")
                
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Binance WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error in Binance kline stream: {e}")
        finally:
            await self.disconnect()
    
    @property
    def last_price(self) -> Optional[Decimal]:
        """Get last received price."""
        return self._last_price
    
    @property
    def last_update(self) -> Optional[datetime]:
        """Get timestamp of last update."""
        return self._last_update
    
    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._is_running and self.websocket is not None
    
    async def health_check(self) -> bool:
        """Check if WebSocket is healthy."""
        return self.is_connected and self._last_price is not None


# Singleton instance
_binance_instance: Optional[BinanceWebSocketSource] = None

def get_binance_source() -> BinanceWebSocketSource:
    """Get singleton instance of Binance WebSocket source."""
    global _binance_instance
    if _binance_instance is None:
        _binance_instance = BinanceWebSocketSource()
    return _binance_instance