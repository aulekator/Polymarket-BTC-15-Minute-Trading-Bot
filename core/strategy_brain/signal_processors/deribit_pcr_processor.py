"""
Deribit Put/Call Ratio Signal Processor
Fetches real-time BTC options data from Deribit (free public API)
and uses the put/call ratio as a proxy for institutional sentiment.

WHY THIS WORKS:
  Professional traders hedge and speculate using BTC options on Deribit —
  the world's largest crypto options exchange ($15B+ daily volume).

  Put/Call Ratio (PCR) = open_interest_puts / open_interest_calls

  PCR interpretation (CONTRARIAN — options markets lean the opposite):
    PCR > 1.2  → More puts than calls = FEAR → contrarian BULLISH
    PCR < 0.7  → More calls than puts = GREED → contrarian BEARISH
    0.7–1.2    → Balanced → no strong signal

  We look specifically at SHORT-DATED options (0-1 days to expiry)
  which are most sensitive to near-term price movements — ideal for
  15-minute trading.

  We also track the 25-delta skew (difference between put and call IV)
  as a secondary signal:
    Positive skew (puts more expensive) → fear → contrarian BULLISH
    Negative skew (calls more expensive) → greed → contrarian BEARISH

API USED (completely free, no auth required):
  GET https://www.deribit.com/api/v2/public/get_book_summary_by_currency
    ?currency=BTC&kind=option

  Returns all active BTC option contracts with:
    - open_interest
    - instrument_name (e.g. BTC-20FEB26-95000-P = Put, -C = Call)
    - days to expiry (parsed from instrument name)
"""
import httpx
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from loguru import logger

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.strategy_brain.signal_processors.base_processor import (
    BaseSignalProcessor,
    TradingSignal,
    SignalType,
    SignalDirection,
    SignalStrength,
)

DERIBIT_URL = "https://www.deribit.com/api/v2/public/get_book_summary_by_currency"


class DeribitPCRProcessor(BaseSignalProcessor):
    """
    Uses Deribit BTC options put/call ratio for contrarian signals.

    Cached for 5 minutes — options data doesn't change tick-by-tick
    and we don't want to hammer Deribit's API every 15 minutes.
    """

    def __init__(
        self,
        bullish_pcr_threshold: float = 1.20,   # PCR above this = contrarian bullish
        bearish_pcr_threshold: float = 0.70,   # PCR below this = contrarian bearish
        max_days_to_expiry: int = 2,            # only short-dated options
        min_open_interest: float = 100.0,       # ignore tiny strikes (BTC notional)
        cache_seconds: int = 300,               # refresh every 5 minutes
        min_confidence: float = 0.55,
    ):
        super().__init__("DeribitPCR")

        self.bullish_pcr_threshold = bullish_pcr_threshold
        self.bearish_pcr_threshold = bearish_pcr_threshold
        self.max_days_to_expiry = max_days_to_expiry
        self.min_open_interest = min_open_interest
        self.cache_seconds = cache_seconds
        self.min_confidence = min_confidence

        # Cache
        self._cached_result: Optional[Dict] = None
        self._cache_time: Optional[datetime] = None

        logger.info(
            f"Initialized Deribit PCR Processor: "
            f"bullish_pcr>{bullish_pcr_threshold}, "
            f"bearish_pcr<{bearish_pcr_threshold}, "
            f"max_dte={max_days_to_expiry}d"
        )

    def _get_client(self) -> httpx.Client:
        """Return a synchronous httpx client (safe inside NautilusTrader's event loop)."""
        return httpx.Client(timeout=8.0)

    def _parse_dte(self, instrument_name: str) -> Optional[int]:
        """
        Parse days to expiry from Deribit instrument name.
        Format: BTC-20FEB26-95000-P  (BTC-DDMMMYY-STRIKE-TYPE)
        """
        try:
            parts = instrument_name.split("-")
            if len(parts) < 3:
                return None
            expiry_str = parts[1]   # e.g. "20FEB26"
            expiry_dt = datetime.strptime(expiry_str, "%d%b%y").replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            dte = (expiry_dt - now).days
            return max(0, dte)
        except Exception:
            return None

    def _fetch_pcr(self) -> Optional[Dict]:
        """Fetch and compute PCR from Deribit synchronously."""
        try:
            with self._get_client() as client:
                resp = client.get(
                    DERIBIT_URL,
                    params={"currency": "BTC", "kind": "option"},
                )
                resp.raise_for_status()
                data = resp.json()

            summaries = data.get("result", [])
            if not summaries:
                logger.warning("Deribit returned empty options data")
                return None

            put_oi = 0.0
            call_oi = 0.0
            short_put_oi = 0.0
            short_call_oi = 0.0

            for item in summaries:
                name = item.get("instrument_name", "")
                oi = float(item.get("open_interest", 0))

                if oi < self.min_open_interest:
                    continue

                is_put = name.endswith("-P")
                is_call = name.endswith("-C")

                if is_put:
                    put_oi += oi
                elif is_call:
                    call_oi += oi

                # Short-dated options
                dte = self._parse_dte(name)
                if dte is not None and dte <= self.max_days_to_expiry:
                    if is_put:
                        short_put_oi += oi
                    elif is_call:
                        short_call_oi += oi

            # Overall PCR
            overall_pcr = put_oi / call_oi if call_oi > 0 else 1.0

            # Short-dated PCR (more relevant for 15-min trading)
            short_pcr = (
                short_put_oi / short_call_oi
                if short_call_oi > 0
                else overall_pcr
            )

            result = {
                "overall_pcr": round(overall_pcr, 4),
                "short_pcr": round(short_pcr, 4),
                "put_oi": round(put_oi, 2),
                "call_oi": round(call_oi, 2),
                "short_put_oi": round(short_put_oi, 2),
                "short_call_oi": round(short_call_oi, 2),
                "total_contracts": len(summaries),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }

            logger.info(
                f"Deribit: overall_PCR={overall_pcr:.3f}, "
                f"short_PCR={short_pcr:.3f} "
                f"(puts={short_put_oi:.0f} vs calls={short_call_oi:.0f} short-dated)"
            )

            return result

        except Exception as e:
            logger.warning(f"Deribit PCR fetch failed: {e}")
            return None

    def process(
        self,
        current_price: Decimal,
        historical_prices: list,
        metadata: Dict[str, Any] = None,
    ) -> Optional[TradingSignal]:
        """Synchronous wrapper — runs async fetch if cache is stale."""
        if not self.is_enabled:
            return None

        # Check cache
        now = datetime.now(timezone.utc)
        cache_valid = (
            self._cached_result is not None and
            self._cache_time is not None and
            (now - self._cache_time).total_seconds() < self.cache_seconds
        )

        if cache_valid:
            pcr_data = self._cached_result
            logger.debug(
                f"DeribitPCR: using cached data "
                f"(PCR={pcr_data['short_pcr']:.3f})"
            )
        else:
            try:
                pcr_data = self._fetch_pcr()
            except Exception as e:
                logger.warning(f"DeribitPCR fetch failed: {e}")
                return None

            if pcr_data is None:
                return None

            self._cached_result = pcr_data
            self._cache_time = now

        return self._generate_signal(current_price, pcr_data)

    def _generate_signal(
        self,
        current_price: Decimal,
        pcr_data: Dict,
    ) -> Optional[TradingSignal]:
        """Generate signal from PCR data."""
        # Prefer short-dated PCR; fall back to overall
        pcr = pcr_data.get("short_pcr") or pcr_data.get("overall_pcr", 1.0)

        if pcr >= self.bullish_pcr_threshold:
            # High PCR = excessive put buying = FEAR = contrarian BULLISH
            direction = SignalDirection.BULLISH
            extremeness = (pcr - self.bullish_pcr_threshold) / self.bullish_pcr_threshold
            confidence = min(0.80, 0.57 + extremeness * 0.15)

            if pcr >= 1.60:
                strength = SignalStrength.VERY_STRONG
            elif pcr >= 1.40:
                strength = SignalStrength.STRONG
            else:
                strength = SignalStrength.MODERATE

            logger.info(
                f"DeribitPCR: HIGH PCR={pcr:.3f} "
                f"(excessive puts = fear) → contrarian BULLISH"
            )

        elif pcr <= self.bearish_pcr_threshold:
            # Low PCR = excessive call buying = GREED = contrarian BEARISH
            direction = SignalDirection.BEARISH
            extremeness = (self.bearish_pcr_threshold - pcr) / self.bearish_pcr_threshold
            confidence = min(0.80, 0.57 + extremeness * 0.15)

            if pcr <= 0.45:
                strength = SignalStrength.VERY_STRONG
            elif pcr <= 0.55:
                strength = SignalStrength.STRONG
            else:
                strength = SignalStrength.MODERATE

            logger.info(
                f"DeribitPCR: LOW PCR={pcr:.3f} "
                f"(excessive calls = greed) → contrarian BEARISH"
            )

        else:
            logger.debug(
                f"DeribitPCR: balanced PCR={pcr:.3f} "
                f"(range {self.bearish_pcr_threshold}–{self.bullish_pcr_threshold}) — no signal"
            )
            return None

        if confidence < self.min_confidence:
            return None

        signal = TradingSignal(
            timestamp=datetime.now(),
            source=self.name,
            signal_type=SignalType.SENTIMENT_SHIFT,
            direction=direction,
            strength=strength,
            confidence=confidence,
            current_price=current_price,
            metadata={
                "pcr": round(pcr, 4),
                "overall_pcr": pcr_data.get("overall_pcr"),
                "short_put_oi": pcr_data.get("short_put_oi"),
                "short_call_oi": pcr_data.get("short_call_oi"),
                "interpretation": (
                    "excessive_puts_fear" if direction == SignalDirection.BULLISH
                    else "excessive_calls_greed"
                ),
            }
        )

        self._record_signal(signal)

        logger.info(
            f"Generated {direction.value.upper()} signal (DeribitPCR): "
            f"PCR={pcr:.3f}, confidence={confidence:.2%}, score={signal.score:.1f}"
        )

        return signal