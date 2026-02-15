"""
Solana RPC Data Source
Connects to Solana blockchain for on-chain BTC/crypto data
"""
import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any, List
import httpx
from loguru import logger


class SolanaRPCDataSource:
    """
    Solana RPC data source.
    
    Note: While Solana doesn't have native BTC, it can provide:
    - Wrapped BTC (wBTC/renBTC) on-chain data
    - DEX price feeds
    - Oracle data (Pyth Network)
    - Transaction volume metrics
    """
    
    def __init__(
        self,
        rpc_url: str = "https://api.mainnet-beta.solana.com",
        use_pyth: bool = True,
    ):
        """
        Initialize Solana RPC source.
        
        Args:
            rpc_url: Solana RPC endpoint
            use_pyth: Whether to use Pyth Network for price data
        """
        self.rpc_url = rpc_url
        self.use_pyth = use_pyth
        self.session: Optional[httpx.AsyncClient] = None
        
        # Pyth BTC/USD price feed address (mainnet)
        self.pyth_btc_address = "GVXRSBjFk6e6J3NbVPXohDJetcTjaeeuykUpbQF8UoMU"
        
        # Cache
        self._last_price: Optional[Decimal] = None
        self._last_update: Optional[datetime] = None
        
        logger.info("Initialized Solana RPC data source")
    
    async def connect(self) -> bool:
        """
        Connect to Solana RPC.
        
        Returns:
            True if connection successful
        """
        try:
            self.session = httpx.AsyncClient(
                timeout=30.0,
                headers={"Content-Type": "application/json"}
            )
            
            # Test connection - get current slot
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSlot"
            }
            
            response = await self.session.post(self.rpc_url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            if "result" in result:
                logger.info(f"✓ Connected to Solana RPC (Slot: {result['result']})")
                return True
            else:
                logger.error("Solana RPC returned unexpected response")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to Solana RPC: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Close connection."""
        if self.session:
            await self.session.aclose()
            logger.info("Disconnected from Solana RPC")
    
    async def get_pyth_price(self) -> Optional[Decimal]:
        """
        Get BTC price from Pyth Network oracle.
        
        Returns:
            BTC price or None if error
        """
        if not self.use_pyth:
            return None
        
        try:
            # Get Pyth account data
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    self.pyth_btc_address,
                    {"encoding": "base64"}
                ]
            }
            
            response = await self.session.post(self.rpc_url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            
            # Note: Parsing Pyth data requires their SDK
            # This is a simplified placeholder
            # In production, use: from pyth_sdk import PythClient
            
            if "result" in result and result["result"]["value"]:
                logger.debug("Fetched Pyth price data (parsing requires Pyth SDK)")
                # Placeholder - would need actual Pyth parsing
                return None
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching Pyth price: {e}")
            return None
    
    async def get_slot(self) -> Optional[int]:
        """
        Get current slot number.
        
        Returns:
            Current slot or None
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSlot"
            }
            
            response = await self.session.post(self.rpc_url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            return result.get("result")
            
        except Exception as e:
            logger.error(f"Error fetching slot: {e}")
            return None
    
    async def get_block_time(self, slot: int) -> Optional[datetime]:
        """
        Get block timestamp.
        
        Args:
            slot: Slot number
            
        Returns:
            Block timestamp
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBlockTime",
                "params": [slot]
            }
            
            response = await self.session.post(self.rpc_url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            timestamp = result.get("result")
            
            if timestamp:
                return datetime.fromtimestamp(timestamp)
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching block time: {e}")
            return None
    
    async def get_token_supply(self, token_mint: str) -> Optional[Dict[str, Any]]:
        """
        Get token supply information.
        
        Args:
            token_mint: Token mint address
            
        Returns:
            Supply information
        """
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenSupply",
                "params": [token_mint]
            }
            
            response = await self.session.post(self.rpc_url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            
            if "result" in result and "value" in result["result"]:
                value = result["result"]["value"]
                return {
                    "amount": value["amount"],
                    "decimals": value["decimals"],
                    "ui_amount": value["uiAmount"],
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching token supply: {e}")
            return None
    
    async def get_network_stats(self) -> Optional[Dict[str, Any]]:
        """
        Get Solana network statistics.
        
        Returns:
            Network stats dict
        """
        try:
            # Get current slot
            slot = await self.get_slot()
            if not slot:
                return None
            
            # Get block time
            block_time = await self.get_block_time(slot)
            
            # Get performance samples
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getRecentPerformanceSamples",
                "params": [1]
            }
            
            response = await self.session.post(self.rpc_url, json=payload)
            response.raise_for_status()
            
            result = response.json()
            
            if "result" in result and len(result["result"]) > 0:
                perf = result["result"][0]
                
                return {
                    "timestamp": block_time or datetime.now(),
                    "current_slot": slot,
                    "num_transactions": perf.get("numTransactions"),
                    "sample_period_secs": perf.get("samplePeriodSecs"),
                    "tps": perf.get("numTransactions", 0) / max(perf.get("samplePeriodSecs", 1), 1),
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching network stats: {e}")
            return None
    
    @property
    def last_price(self) -> Optional[Decimal]:
        """Get cached last price."""
        return self._last_price
    
    @property
    def last_update(self) -> Optional[datetime]:
        """Get time of last price update."""
        return self._last_update
    
    async def health_check(self) -> bool:
        """
        Check if data source is healthy.
        
        Returns:
            True if healthy
        """
        try:
            slot = await self.get_slot()
            return slot is not None
        except:
            return False


# Singleton instance
_solana_instance: Optional[SolanaRPCDataSource] = None

def get_solana_source() -> SolanaRPCDataSource:
    """Get singleton instance of Solana RPC data source."""
    global _solana_instance
    if _solana_instance is None:
        _solana_instance = SolanaRPCDataSource()
    return _solana_instance