"""
Enhanced patch for Polymarket gamma_markets.py and provider.py
- Fixes array parameter handling in gamma_markets.py
- Forces load_all_async to use Gamma API with time filters
"""

import os
from typing import Any, Dict, List, Tuple, Union
import logging
import asyncio

logger = logging.getLogger(__name__)


def apply_gamma_markets_patch():
    """
    Monkey-patch both gamma_markets.py and provider.py to properly handle filtering.
    """
    try:
        # Import the modules we need to patch
        from nautilus_trader.adapters.polymarket.common import gamma_markets
        from nautilus_trader.adapters.polymarket import providers
        from nautilus_trader.core.nautilus_pyo3 import HttpClient
        
        logger.info("=" * 80)
        logger.info("Applying enhanced patches for Polymarket filtering")
        logger.info("=" * 80)
        
        # ===== PATCH 1: Fix gamma_markets.py array parameter handling =====
        
        def patched_build_markets_query(filters: Dict[str, Any] | None = None) -> Dict[str, Any]:
            """
            Patched version that properly handles array parameters.
            """
            params: Dict[str, Any] = {}
            if not filters:
                return params

            if filters.get("is_active") is True:
                params["active"] = "true"
                params["archived"] = "false"
                params["closed"] = "false"

            # Handle scalar parameters
            scalar_keys = (
                "active",
                "archived",
                "closed",
                "limit",
                "offset",
                "order",
                "ascending",
                "liquidity_num_min",
                "liquidity_num_max",
                "volume_num_min",
                "volume_num_max",
                "start_date_min",
                "start_date_max",
                "end_date_min",
                "end_date_max",
                "tag_id",
                "related_tags",
            )
            for key in scalar_keys:
                if key in filters and filters[key] is not None:
                    params[key] = filters[key]

            # Handle array parameters
            array_keys = (
                "id",
                "slug",
                "clob_token_ids",
                "condition_ids",
                "question_ids",
                "market_maker_address",
            )
            
            for key in array_keys:
                if key in filters and filters[key] is not None:
                    value = filters[key]
                    if isinstance(value, (tuple, list)):
                        params[key] = list(value)
                    else:
                        params[key] = [value]
                    
                    if key == "slug" and params[key]:
                        logger.debug(f"Added {len(params[key])} slug filters")

            return params
        
        # Apply gamma_markets patch
        gamma_markets.build_markets_query = patched_build_markets_query
        logger.info("✓ Patched gamma_markets.build_markets_query (array parameter handling)")
        
        # ===== PATCH 2: Replace load_all_async to force Gamma API usage =====
        
        async def patched_load_all_async(self, filters: dict | None = None) -> None:
            """
            FORCE using Gamma API for all market loading when use_gamma_markets=True.
            This completely bypasses the broken CLOB API implementation.
            """
            # Log what we're doing
            self._log.info("=" * 80)
            self._log.info("LOADING MARKETS VIA GAMMA API (PATCHED)")
            
            if filters:
                self._log.info(f"Filters: {filters}")
                
                # Log time filters specifically
                if filters.get("end_date_min"):
                    self._log.info(f"  end_date_min: {filters['end_date_min']}")
                if filters.get("end_date_max"):
                    self._log.info(f"  end_date_max: {filters['end_date_max']}")
            else:
                self._log.info("No filters applied")
            
            self._log.info("=" * 80)
            
            # Always use Gamma API when use_gamma_markets=True
            if self._config.use_gamma_markets:
                await self._load_all_using_gamma_markets(filters)
            else:
                # Fall back to original method
                self._log.warning("Falling back to CLOB API (slow, may ignore filters)")
                await self._load_markets([], filters)
        
        async def _load_all_using_gamma_markets(self, filters: dict | None = None) -> None:
            """
            Load all instruments using Gamma API with proper server-side filtering.
            This is the CORRECT implementation that respects time filters.
            """
            filters = filters.copy() if filters is not None else {}
            
            # Set reasonable defaults
            if "limit" not in filters:
                filters["limit"] = 1000  # Get as many as possible per request
            
            self._log.info(f"Requesting markets from Gamma API with filters: {filters}")
            
            try:
                markets = await gamma_markets.list_markets(
                    http_client=self._http_client, 
                    filters=filters,
                    timeout=120.0
                )
                
                self._log.info(f"✓ Gamma API returned {len(markets)} markets")
                
                if not markets:
                    self._log.warning("No markets found with current filters")
                    self._log.warning("Check that:")
                    self._log.warning("  1. Markets exist with these expiration times")
                    self._log.warning("  2. Filters are correctly formatted")
                    return
                
                # Count markets by type for debugging
                btc_count = 0
                eth_count = 0
                sol_count = 0
                
                for market in markets:
                    slug = market.get('slug', '')
                    if 'btc' in slug.lower():
                        btc_count += 1
                    elif 'eth' in slug.lower():
                        eth_count += 1
                    elif 'sol' in slug.lower():
                        sol_count += 1
                
                self._log.info(f"Market breakdown: {btc_count} BTC, {eth_count} ETH, {sol_count} SOL, {len(markets) - btc_count - eth_count - sol_count} other")
                
                # Process each market
                loaded_count = 0
                for market in markets:
                    try:
                        normalized_market = gamma_markets.normalize_gamma_market_to_clob_format(market)
                        
                        # Log BTC markets specifically
                        slug = market.get('slug', '')
                        if 'btc' in slug.lower() and '15m' in slug.lower():
                            self._log.info(f"✓ Found BTC 15-min market: {slug}")
                        
                        for token_info in normalized_market.get("tokens", []):
                            token_id = token_info["token_id"]
                            if not token_id:
                                continue
                            outcome = token_info["outcome"]
                            self._load_instrument(normalized_market, token_id, outcome)
                            loaded_count += 1
                    except Exception as e:
                        self._log.error(f"Error processing market {market.get('slug', 'unknown')}: {e}")
                        continue
                
                self._log.info(f"Successfully loaded {loaded_count} instruments from {len(markets)} markets")
                
                if btc_count > 0:
                    self._log.info(f"✓ BTC markets found and loaded!")
                else:
                    self._log.warning("No BTC markets found in this batch")
                    
            except Exception as e:
                self._log.error(f"Gamma API request failed: {e}")
                import traceback
                traceback.print_exc()
        
        # Apply provider patches
        providers.PolymarketInstrumentProvider.load_all_async = patched_load_all_async
        providers.PolymarketInstrumentProvider._load_all_using_gamma_markets = _load_all_using_gamma_markets
        
        logger.info("✓ Patched PolymarketInstrumentProvider.load_all_async")
        logger.info("  - Now FORCES Gamma API usage with proper filtering")
        logger.info("  - Time-based filters should now work correctly")
        logger.info("=" * 80)
        
        return True
        
    except ImportError as e:
        logger.error(f"Failed to import modules: {e}")
        logger.error("Make sure nautilus_trader is installed")
        return False
    except Exception as e:
        logger.error(f"Failed to apply patch: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_patch():
    """Verify that the patch is working."""
    try:
        from nautilus_trader.adapters.polymarket.common import gamma_markets
        from nautilus_trader.adapters.polymarket import providers
        
        logger.info("=" * 80)
        logger.info("VERIFYING PATCHES")
        logger.info("=" * 80)
        
        # Test gamma_markets array handling
        test_filters = {
            "active": True,
            "closed": False,
            "archived": False,
            "slug": ("test-slug-1", "test-slug-2"),
            "end_date_min": "2026-01-01T00:00:00Z",
        }
        
        params = gamma_markets.build_markets_query(test_filters)
        logger.info("Gamma markets query builder test:")
        logger.info(f"  Input filters: {test_filters}")
        logger.info(f"  Output params: {params}")
        
        # Check provider methods
        has_patched = hasattr(providers.PolymarketInstrumentProvider, '_load_all_using_gamma_markets')
        logger.info(f"Provider has patched method: {has_patched}")
        
        logger.info("=" * 80)
        
        return has_patched
        
    except Exception as e:
        logger.error(f"Failed to verify patch: {e}")
        return False