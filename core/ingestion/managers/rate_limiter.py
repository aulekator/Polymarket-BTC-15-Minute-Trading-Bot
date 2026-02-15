"""
Rate Limiter
Prevents exceeding API rate limits
"""
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional
from collections import deque
from loguru import logger


class RateLimiter:
    """
    Token bucket rate limiter.
    
    Ensures we don't exceed API rate limits by:
    - Tracking requests per time window
    - Blocking when limit reached
    - Auto-replenishing tokens
    """
    
    def __init__(
        self,
        name: str,
        max_requests: int,
        time_window: int = 60,  # seconds
    ):
        """
        Initialize rate limiter.
        
        Args:
            name: Limiter name for logging
            max_requests: Maximum requests allowed in time window
            time_window: Time window in seconds
        """
        self.name = name
        self.max_requests = max_requests
        self.time_window = time_window
        
        # Track request timestamps
        self._requests: deque = deque()
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
        
        logger.info(
            f"Initialized rate limiter '{name}': "
            f"{max_requests} requests per {time_window}s"
        )
    
    async def acquire(self, wait: bool = True) -> bool:
        """
        Acquire permission to make a request.
        
        Args:
            wait: If True, wait for available slot. If False, return immediately.
            
        Returns:
            True if permission granted, False if limit reached (when wait=False)
        """
        async with self._lock:
            now = datetime.now()
            
            # Remove old requests outside time window
            cutoff_time = now - timedelta(seconds=self.time_window)
            
            while self._requests and self._requests[0] < cutoff_time:
                self._requests.popleft()
            
            # Check if we can make a request
            if len(self._requests) < self.max_requests:
                self._requests.append(now)
                return True
            
            # Limit reached
            if not wait:
                logger.warning(
                    f"Rate limit reached for '{self.name}': "
                    f"{len(self._requests)}/{self.max_requests} in {self.time_window}s"
                )
                return False
            
            # Wait until oldest request expires
            oldest_request = self._requests[0]
            wait_time = (oldest_request + timedelta(seconds=self.time_window) - now).total_seconds()
            
            if wait_time > 0:
                logger.info(
                    f"Rate limit for '{self.name}' - waiting {wait_time:.1f}s..."
                )
                await asyncio.sleep(wait_time)
            
            # Retry
            return await self.acquire(wait=True)
    
    def get_remaining(self) -> int:
        """
        Get number of remaining requests in current window.
        
        Returns:
            Number of requests available
        """
        now = datetime.now()
        cutoff_time = now - timedelta(seconds=self.time_window)
        
        # Count requests in current window
        current_requests = sum(
            1 for req_time in self._requests
            if req_time >= cutoff_time
        )
        
        return max(0, self.max_requests - current_requests)
    
    def get_reset_time(self) -> Optional[datetime]:
        """
        Get time when rate limit resets.
        
        Returns:
            Reset time or None if not limited
        """
        if not self._requests:
            return None
        
        oldest_request = self._requests[0]
        return oldest_request + timedelta(seconds=self.time_window)
    
    def get_stats(self) -> Dict[str, any]:
        """Get rate limiter statistics."""
        now = datetime.now()
        cutoff_time = now - timedelta(seconds=self.time_window)
        
        current_requests = sum(
            1 for req_time in self._requests
            if req_time >= cutoff_time
        )
        
        reset_time = self.get_reset_time()
        
        return {
            "name": self.name,
            "max_requests": self.max_requests,
            "time_window_seconds": self.time_window,
            "current_requests": current_requests,
            "remaining": self.max_requests - current_requests,
            "reset_time": reset_time.isoformat() if reset_time else None,
            "utilization_percent": (current_requests / self.max_requests) * 100,
        }
    
    def reset(self) -> None:
        """Reset the rate limiter (clear all requests)."""
        self._requests.clear()
        logger.info(f"Reset rate limiter '{self.name}'")


class MultiSourceRateLimiter:
    """
    Manages rate limiters for multiple API sources.
    """
    
    def __init__(self):
        """Initialize multi-source rate limiter."""
        self.limiters: Dict[str, RateLimiter] = {}
        
        # Default limits based on API documentation
        self._setup_default_limiters()
        
        logger.info("Initialized multi-source rate limiter")
    
    def _setup_default_limiters(self) -> None:
        """Setup default rate limiters for known APIs."""
        # Coinbase: 10 req/sec public, 15 req/sec authenticated
        # Using conservative 8 req/sec = 480 req/min
        self.add_limiter("coinbase", max_requests=480, time_window=60)
        
        # Binance: 1200 req/min on REST (WebSocket has no limit)
        self.add_limiter("binance", max_requests=1000, time_window=60)
        
        # Fear & Greed: No documented limit, being conservative
        self.add_limiter("fear_greed", max_requests=60, time_window=60)
        
        # Solana RPC: Depends on provider, being conservative
        self.add_limiter("solana", max_requests=100, time_window=60)
    
    def add_limiter(
        self,
        source: str,
        max_requests: int,
        time_window: int = 60
    ) -> RateLimiter:
        """
        Add or update a rate limiter for a source.
        
        Args:
            source: Source name
            max_requests: Max requests per window
            time_window: Time window in seconds
            
        Returns:
            Created rate limiter
        """
        limiter = RateLimiter(source, max_requests, time_window)
        self.limiters[source] = limiter
        return limiter
    
    async def acquire(self, source: str, wait: bool = True) -> bool:
        """
        Acquire permission for a source.
        
        Args:
            source: Source name
            wait: Whether to wait if limit reached
            
        Returns:
            True if permission granted
        """
        if source not in self.limiters:
            logger.warning(f"No rate limiter for '{source}', allowing request")
            return True
        
        return await self.limiters[source].acquire(wait=wait)
    
    def get_stats(self, source: Optional[str] = None) -> Dict[str, any]:
        """
        Get rate limiter statistics.
        
        Args:
            source: Specific source or None for all
            
        Returns:
            Statistics dict
        """
        if source:
            if source in self.limiters:
                return self.limiters[source].get_stats()
            else:
                return {}
        else:
            return {
                name: limiter.get_stats()
                for name, limiter in self.limiters.items()
            }
    
    def reset_all(self) -> None:
        """Reset all rate limiters."""
        for limiter in self.limiters.values():
            limiter.reset()
        logger.info("Reset all rate limiters")


# Singleton instance
_rate_limiter_instance: Optional[MultiSourceRateLimiter] = None

def get_rate_limiter() -> MultiSourceRateLimiter:
    """Get singleton instance of rate limiter."""
    global _rate_limiter_instance
    if _rate_limiter_instance is None:
        _rate_limiter_instance = MultiSourceRateLimiter()
    return _rate_limiter_instance