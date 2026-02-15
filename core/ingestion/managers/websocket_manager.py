"""
WebSocket Connection Manager
Handles WebSocket connections with auto-reconnection and error handling
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Callable, Any
from enum import Enum
from loguru import logger


class ConnectionState(Enum):
    """WebSocket connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class WebSocketManager:
    """
    Manages WebSocket connections with:
    - Auto-reconnection
    - Exponential backoff
    - Connection health monitoring
    - Message buffering
    """
    
    def __init__(
        self,
        name: str,
        connect_func: Callable,
        stream_func: Callable,
        max_reconnect_attempts: int = 5,
        initial_backoff: float = 1.0,
        max_backoff: float = 60.0,
    ):
        """
        Initialize WebSocket manager.
        
        Args:
            name: Connection name for logging
            connect_func: Async function to establish connection
            stream_func: Async function to stream data
            max_reconnect_attempts: Max reconnection attempts before giving up
            initial_backoff: Initial backoff delay in seconds
            max_backoff: Maximum backoff delay in seconds
        """
        self.name = name
        self.connect_func = connect_func
        self.stream_func = stream_func
        self.max_reconnect_attempts = max_reconnect_attempts
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        
        # State
        self.state = ConnectionState.DISCONNECTED
        self.reconnect_attempts = 0
        self.last_message_time: Optional[datetime] = None
        self.last_error: Optional[str] = None
        
        # Tasks
        self._stream_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        
        # Callbacks
        self.on_connected: Optional[Callable] = None
        self.on_disconnected: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        self.on_message: Optional[Callable] = None
        
        logger.info(f"Initialized WebSocket manager: {name}")
    
    async def connect(self) -> bool:
        """
        Connect to WebSocket.
        
        Returns:
            True if connection successful
        """
        try:
            self.state = ConnectionState.CONNECTING
            logger.info(f"{self.name}: Connecting...")
            
            # Call connect function
            success = await self.connect_func()
            
            if success:
                self.state = ConnectionState.CONNECTED
                self.reconnect_attempts = 0
                self.last_message_time = datetime.now()
                
                logger.info(f"{self.name}: Connected successfully")
                
                if self.on_connected:
                    await self.on_connected()
                
                return True
            else:
                self.state = ConnectionState.FAILED
                logger.error(f"{self.name}: Connection failed")
                return False
                
        except Exception as e:
            self.state = ConnectionState.FAILED
            self.last_error = str(e)
            logger.error(f"{self.name}: Connection error: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        logger.info(f"{self.name}: Disconnecting...")
        
        # Cancel tasks
        if self._stream_task:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
        
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        self.state = ConnectionState.DISCONNECTED
        
        if self.on_disconnected:
            await self.on_disconnected()
        
        logger.info(f"{self.name}: Disconnected")
    
    async def start_streaming(self) -> None:
        """Start streaming data with auto-reconnection."""
        logger.info(f"{self.name}: Starting stream with auto-reconnection...")
        
        # Start streaming task
        self._stream_task = asyncio.create_task(self._stream_with_reconnect())
        
        # Start health check task
        self._health_check_task = asyncio.create_task(self._monitor_health())
    
    async def _stream_with_reconnect(self) -> None:
        """Stream data with automatic reconnection on failure."""
        while True:
            try:
                # Connect if not connected
                if self.state != ConnectionState.CONNECTED:
                    if not await self.connect():
                        # Connection failed, wait before retry
                        await self._backoff_and_retry()
                        continue
                
                # Start streaming
                logger.info(f"{self.name}: Starting data stream...")
                await self.stream_func()
                
            except asyncio.CancelledError:
                logger.info(f"{self.name}: Stream cancelled")
                break
                
            except Exception as e:
                self.last_error = str(e)
                logger.error(f"{self.name}: Stream error: {e}")
                
                if self.on_error:
                    await self.on_error(e)
                
                # Attempt reconnection
                self.state = ConnectionState.RECONNECTING
                await self._backoff_and_retry()
    
    async def _backoff_and_retry(self) -> None:
        """Wait with exponential backoff before retry."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(
                f"{self.name}: Max reconnect attempts ({self.max_reconnect_attempts}) reached"
            )
            self.state = ConnectionState.FAILED
            return
        
        # Calculate backoff delay
        backoff = min(
            self.initial_backoff * (2 ** self.reconnect_attempts),
            self.max_backoff
        )
        
        self.reconnect_attempts += 1
        
        logger.warning(
            f"{self.name}: Reconnect attempt {self.reconnect_attempts}/{self.max_reconnect_attempts} "
            f"in {backoff:.1f}s..."
        )
        
        await asyncio.sleep(backoff)
    
    async def _monitor_health(self, check_interval: int = 30) -> None:
        """
        Monitor connection health.
        
        Args:
            check_interval: Seconds between health checks
        """
        while True:
            try:
                await asyncio.sleep(check_interval)
                
                if self.state != ConnectionState.CONNECTED:
                    continue
                
                # Check if we've received messages recently
                if self.last_message_time:
                    time_since_message = datetime.now() - self.last_message_time
                    
                    if time_since_message > timedelta(seconds=check_interval * 2):
                        logger.warning(
                            f"{self.name}: No messages for {time_since_message.seconds}s, "
                            "connection may be stale"
                        )
                        
                        # Force reconnection
                        self.state = ConnectionState.RECONNECTING
                        await self.disconnect()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"{self.name}: Health check error: {e}")
    
    def update_last_message_time(self) -> None:
        """Update timestamp of last received message."""
        self.last_message_time = datetime.now()
    
    @property
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self.state == ConnectionState.CONNECTED
    
    @property
    def is_healthy(self) -> bool:
        """Check if connection is healthy (connected and receiving data)."""
        if not self.is_connected:
            return False
        
        if not self.last_message_time:
            return False
        
        # Consider healthy if received message in last 60 seconds
        time_since_message = datetime.now() - self.last_message_time
        return time_since_message < timedelta(seconds=60)
    
    def get_stats(self) -> dict:
        """Get connection statistics."""
        return {
            "name": self.name,
            "state": self.state.value,
            "reconnect_attempts": self.reconnect_attempts,
            "last_message_time": self.last_message_time.isoformat() if self.last_message_time else None,
            "is_healthy": self.is_healthy,
            "last_error": self.last_error,
        }