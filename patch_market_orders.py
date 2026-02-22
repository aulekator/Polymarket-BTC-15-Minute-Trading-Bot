"""
Patch for PolymarketExecutionClient to support $1 market buys.

The Polymarket adapter normally requires quote_quantity=True for BUY market orders,
but our strategy sends token quantities (quote_quantity=False).
This patch intercepts BUY market orders and forces them to use the configured
USD amount ($1 default) via the create_market_order API call.

How Polymarket market orders work:
  - BUY:  amount = USD to spend  (e.g. 1.0 = spend $1)
  - SELL: amount = tokens to sell (e.g. 5.0 = sell 5 tokens)

Minimum order: $1 USD for market BUY orders (NOT 5 tokens).
The 5-token minimum only applies to LIMIT orders.
"""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

_patch_applied = False


def apply_market_order_patch():
    """Apply monkey patch to PolymarketExecutionClient."""
    global _patch_applied

    if _patch_applied:
        logger.info("Market order patch already applied")
        return True

    try:
        from nautilus_trader.adapters.polymarket.execution import PolymarketExecutionClient
        from nautilus_trader.adapters.polymarket.common.symbol import get_polymarket_token_id
        from nautilus_trader.adapters.polymarket.http.conversion import convert_tif_to_polymarket_order_type
        from nautilus_trader.model.enums import OrderSide, order_side_to_str
        from nautilus_trader.common.enums import LogColor
        from py_clob_client.client import MarketOrderArgs, PartialCreateOrderOptions

        # --- Read USD amount from environment (default $1) ---
        _DEFAULT_USD_AMOUNT = float(os.getenv("MARKET_BUY_USD", "1.0"))
        logger.info(f"Market BUY USD amount configured to: ${_DEFAULT_USD_AMOUNT:.2f}")

        async def _patched_submit_market_order(self, command, instrument):
            """
            Patched market order handler.

            For BUY orders:  always use USD amount (default $1) via create_market_order.
            For SELL orders: use token quantity as normal (base-denominated).
            """
            order = command.order

            if order.side == OrderSide.BUY:
                # Read amount each call so live env changes take effect
                usd_amount = float(os.getenv("MARKET_BUY_USD", str(_DEFAULT_USD_AMOUNT)))

                self._log.info(
                    f"[PATCH] BUY market order → using ${usd_amount:.2f} USD "
                    f"(token qty ignored: {float(order.quantity):.6f})",
                    LogColor.MAGENTA,
                )

                order_type = convert_tif_to_polymarket_order_type(order.time_in_force)

                market_order_args = MarketOrderArgs(
                    token_id=get_polymarket_token_id(order.instrument_id),
                    amount=usd_amount,          # ← USD, not tokens
                    side=order_side_to_str(order.side),
                    order_type=order_type,
                )

                neg_risk = self._get_neg_risk_for_instrument(instrument)
                options = PartialCreateOrderOptions(neg_risk=neg_risk)

                signing_start = self._clock.timestamp()
                signed_order = await asyncio.to_thread(
                    self._http_client.create_market_order,
                    market_order_args,
                    options=options,
                )
                interval = self._clock.timestamp() - signing_start
                self._log.info(
                    f"[PATCH] Signed market BUY in {interval:.3f}s (${usd_amount:.2f})",
                    LogColor.BLUE,
                )

                self.generate_order_submitted(
                    strategy_id=order.strategy_id,
                    instrument_id=order.instrument_id,
                    client_order_id=order.client_order_id,
                    ts_event=self._clock.timestamp_ns(),
                )

                await self._post_signed_order(order, signed_order)

            else:
                # SELL: use token quantity (base-denominated), standard behavior
                if order.is_quote_quantity:
                    self._deny_market_order_quantity(
                        order,
                        "Polymarket market SELL orders require base-denominated quantities; "
                        "resubmit with `quote_quantity=False`",
                    )
                    return

                amount = float(order.quantity)
                order_type = convert_tif_to_polymarket_order_type(order.time_in_force)

                market_order_args = MarketOrderArgs(
                    token_id=get_polymarket_token_id(order.instrument_id),
                    amount=amount,
                    side=order_side_to_str(order.side),
                    order_type=order_type,
                )

                neg_risk = self._get_neg_risk_for_instrument(instrument)
                options = PartialCreateOrderOptions(neg_risk=neg_risk)

                signing_start = self._clock.timestamp()
                signed_order = await asyncio.to_thread(
                    self._http_client.create_market_order,
                    market_order_args,
                    options=options,
                )
                interval = self._clock.timestamp() - signing_start
                self._log.info(f"Signed Polymarket market SELL in {interval:.3f}s", LogColor.BLUE)

                self.generate_order_submitted(
                    strategy_id=order.strategy_id,
                    instrument_id=order.instrument_id,
                    client_order_id=order.client_order_id,
                    ts_event=self._clock.timestamp_ns(),
                )

                await self._post_signed_order(order, signed_order)

        # Apply the patch
        PolymarketExecutionClient._submit_market_order = _patched_submit_market_order
        _patch_applied = True
        logger.info("Market order patch applied — BUY orders will use $MARKET_BUY_USD (default $1)")
        return True

    except ImportError as e:
        logger.error(f"Failed to import required modules: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to apply market order patch: {e}")
        import traceback
        traceback.print_exc()
        return False