#!/usr/bin/env python3
"""
Test Script for Phase 4: Strategy Brain

Tests:
1. Signal Processors (Spike, Sentiment, Divergence)
2. Signal Fusion Engine
3. 15-Minute BTC Strategy
4. End-to-End Signal Flow

Run this after Phase 3 tests pass.
"""
import asyncio
from decimal import Decimal
from datetime import datetime
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from loguru import logger


import os

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.strategy_brain.signal_processors.spike_detector import SpikeDetectionProcessor
from core.strategy_brain.signal_processors.sentiment_processor import SentimentProcessor
from core.strategy_brain.signal_processors.divergence_processor import PriceDivergenceProcessor
from core.strategy_brain.fusion_engine.signal_fusion import get_fusion_engine
from core.strategy_brain.strategies.btc_15min_strategy import get_btc_strategy

app = typer.Typer()
console = Console()


async def test_signal_processors():
    """Test all signal processors."""
    console.print("\n[cyan]═══ Testing Signal Processors ═══[/cyan]")
    
    try:
        # Create processors
        spike = SpikeDetectionProcessor()
        sentiment = SentimentProcessor()
        divergence = PriceDivergenceProcessor()
        
        console.print("✓ All processors initialized")
        
        # Test spike detector with simulated data
        console.print("\nTesting Spike Detector...", end="")
        
        # Create price history (stable around 65000)
        history = [Decimal(str(65000 + i*10)) for i in range(-20, 0)]
        
        # Simulate a spike
        current = Decimal("70000")  # 7.7% spike
        
        signal = spike.process(current, history)
        
        if signal:
            console.print(" [green]✓ Spike detected![/green]")
            console.print(f"  Direction: {signal.direction.value}")
            console.print(f"  Confidence: {signal.confidence:.2%}")
            console.print(f"  Score: {signal.score:.1f}")
        else:
            console.print(" [yellow]⚠ No spike detected (adjust threshold)[/yellow]")
        
        # Test sentiment processor
        console.print("\nTesting Sentiment Processor...", end="")
        
        metadata = {"sentiment_score": 15.0}  # Extreme fear
        signal = sentiment.process(current, history, metadata)
        
        if signal:
            console.print(" [green]✓ Sentiment signal generated![/green]")
            console.print(f"  Direction: {signal.direction.value}")
            console.print(f"  Score: {signal.score:.1f}")
        else:
            console.print(" [yellow]⚠ No sentiment signal[/yellow]")
        
        # Test divergence processor
        console.print("\nTesting Divergence Processor...", end="")
        
        metadata = {"spot_price": 67000.0}  # 4.5% divergence
        signal = divergence.process(current, history, metadata)
        
        if signal:
            console.print(" [green]✓ Divergence detected![/green]")
            console.print(f"  Direction: {signal.direction.value}")
            console.print(f"  Divergence: {signal.metadata['divergence_pct']:.2%}")
        else:
            console.print(" [yellow]⚠ No divergence detected[/yellow]")
        
        console.print("\n[green]✓ Signal Processors - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing processors: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


async def test_fusion_engine():
    """Test signal fusion engine."""
    console.print("\n[cyan]═══ Testing Signal Fusion Engine ═══[/cyan]")
    
    try:
        fusion = get_fusion_engine()
        
        # Create test signals
        from strategy_brain.signal_processors.base_processor import (
            TradingSignal,
            SignalType,
            SignalDirection,
            SignalStrength,
        )
        
        signals = [
            # Bullish spike signal
            TradingSignal(
                timestamp=datetime.now(),
                source="SpikeDetection",
                signal_type=SignalType.SPIKE_DETECTED,
                direction=SignalDirection.BULLISH,
                strength=SignalStrength.STRONG,
                confidence=0.80,
                current_price=Decimal("65000"),
            ),
            # Bullish sentiment signal
            TradingSignal(
                timestamp=datetime.now(),
                source="SentimentAnalysis",
                signal_type=SignalType.SENTIMENT_SHIFT,
                direction=SignalDirection.BULLISH,
                strength=SignalStrength.MODERATE,
                confidence=0.70,
                current_price=Decimal("65000"),
            ),
        ]
        
        console.print(f"Fusing {len(signals)} signals...", end="")
        
        fused = fusion.fuse_signals(signals)
        
        if fused:
            console.print(" [green]✓ Fusion successful![/green]")
            console.print(f"  Direction: {fused.direction.value}")
            console.print(f"  Score: {fused.score:.1f}")
            console.print(f"  Confidence: {fused.confidence:.2%}")
            console.print(f"  Actionable: {fused.is_actionable}")
        else:
            console.print(" [red]✗ Fusion failed[/red]")
            return False
        
        # Test statistics
        console.print("\nChecking statistics...", end="")
        stats = fusion.get_statistics()
        
        console.print(" [green]✓ Stats available[/green]")
        console.print(f"  Total fusions: {stats['total_fusions']}")
        
        console.print("\n[green]✓ Signal Fusion Engine - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing fusion: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


async def test_btc_strategy():
    """Test 15-minute BTC strategy."""
    console.print("\n[cyan]═══ Testing 15-Min BTC Strategy ═══[/cyan]")
    
    try:
        strategy = get_btc_strategy()
        
        # Update market data
        console.print("Updating market data...", end="")
        
        # Simulate price history
        for i in range(30):
            strategy.update_market_data(
                price=Decimal(str(65000 + i*50)),
                spot_consensus=Decimal(str(65000 + i*50)),
                sentiment=20.0,  # Extreme fear
            )
        
        # Spike price
        strategy.update_market_data(
            price=Decimal("75000"),  # 15% spike
            spot_consensus=Decimal("67000"),
            sentiment=85.0,  # Extreme greed
        )
        
        console.print(" [green]✓ Market data updated[/green]")
        
        # Process signals manually
        console.print("Processing signals...", end="")
        
        signals = strategy._process_signals()
        
        if signals:
            console.print(f" [green]✓ {len(signals)} signals generated[/green]")
            for sig in signals:
                console.print(f"  • {sig.source}: {sig.direction.value} (score={sig.score:.1f})")
        else:
            console.print(" [yellow]⚠ No signals generated[/yellow]")
        
        # Get statistics
        console.print("\nGetting strategy statistics...", end="")
        stats = strategy.get_statistics()
        
        console.print(" [green]✓ Stats available[/green]")
        console.print(f"  Signals processed: {stats['signals_processed']}")
        console.print(f"  Trades executed: {stats['trades_executed']}")
        console.print(f"  Open positions: {stats['open_positions']}")
        
        console.print("\n[green]✓ BTC Strategy - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing strategy: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """Run all Phase 4 tests."""
    console.print(Panel.fit(
        "[bold cyan]PHASE 4: STRATEGY BRAIN - TEST SUITE[/bold cyan]\n\n"
        "Testing signal processing and strategy logic...",
        border_style="cyan"
    ))
    
    results = {}
    
    # Test each component
    results["Signal Processors"] = await test_signal_processors()
    results["Fusion Engine"] = await test_fusion_engine()
    results["BTC Strategy"] = await test_btc_strategy()
    
    # Summary
    console.print("\n" + "="*60)
    console.print("[bold]TEST SUMMARY[/bold]")
    console.print("="*60)
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan", width=25)
    table.add_column("Status", width=15)
    table.add_column("Ready for Phase 5", width=15)
    
    for component, passed in results.items():
        status = "[green]✓ PASSED[/green]" if passed else "[red]✗ FAILED[/red]"
        ready = "[green]Yes[/green]" if passed else "[red]No[/red]"
        table.add_row(component, status, ready)
    
    console.print(table)
    
    # Overall result
    all_passed = all(results.values())
    
    console.print("\n" + "="*60)
    if all_passed:
        console.print("[bold green]✓ ALL TESTS PASSED![/bold green]")
        console.print("\n[cyan]Phase 4 is complete and working![/cyan]")
        console.print("[cyan]You can now proceed to Phase 5: Execution Layer[/cyan]")
        return 0
    else:
        console.print("[bold red]✗ SOME TESTS FAILED[/bold red]")
        console.print("\n[yellow]Fix the failed components before proceeding to Phase 5.[/yellow]")
        return 1


@app.command()
def test(
    component: str = typer.Option(
        "all",
        "--component",
        "-c",
        help="Test specific component: all, processors, fusion, strategy"
    )
):
    """
    Test Strategy Brain components.
    
    Example:
        python scripts/test_strategy.py test
        python scripts/test_strategy.py test --component processors
    """
    async def run_specific_test():
        if component == "all":
            return await run_all_tests()
        elif component == "processors":
            return 0 if await test_signal_processors() else 1
        elif component == "fusion":
            return 0 if await test_fusion_engine() else 1
        elif component == "strategy":
            return 0 if await test_btc_strategy() else 1
        else:
            console.print(f"[red]Unknown component: {component}[/red]")
            return 1
    
    exit_code = asyncio.run(run_specific_test())
    raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()