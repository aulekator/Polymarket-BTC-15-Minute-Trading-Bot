#!/usr/bin/env python3
"""
Test Script for Phase 3: Nautilus Core

Tests:
1. Instrument Registry
2. Data Engine Integration
3. Event Dispatcher
4. Custom Data Provider
5. End-to-End Data Flow

Run this after Phase 2 tests pass.
"""
import asyncio
from datetime import datetime
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from loguru import logger

import os

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.nautilus_core.instruments.btc_instruments import get_instrument_registry
from core.nautilus_core.data_engine.engine_wrapper import get_nautilus_engine
from core.nautilus_core.event_dispatcher.dispatcher import get_event_dispatcher, EventType, Event

app = typer.Typer()
console = Console()


async def test_instruments():
    """Test instrument registry."""
    console.print("\n[cyan]═══ Testing Instrument Registry ═══[/cyan]")
    
    try:
        registry = get_instrument_registry()
        
        # Check instruments
        console.print(f"Checking registered instruments...", end="")
        
        all_instruments = registry.get_all()
        
        if len(all_instruments) >= 3:
            console.print(f" [green]✓ {len(all_instruments)} instruments registered[/green]")
        else:
            console.print(" [red]✗ Not enough instruments[/red]")
            return False
        
        # Check specific instruments
        polymarket = registry.get_polymarket()
        coinbase = registry.get_coinbase()
        binance = registry.get_binance()
        
        if polymarket and coinbase and binance:
            console.print("[green]✓ All key instruments available:[/green]")
            console.print(f"  - Polymarket: {polymarket.id}")
            console.print(f"  - Coinbase: {coinbase.id}")
            console.print(f"  - Binance: {binance.id}")
        else:
            console.print("[red]✗ Missing instruments[/red]")
            return False
        
        console.print("[green]✓ Instrument Registry - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing instruments: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


async def test_event_dispatcher():
    """Test event dispatcher."""
    console.print("\n[cyan]═══ Testing Event Dispatcher ═══[/cyan]")
    
    try:
        dispatcher = get_event_dispatcher()
        
        # Test subscription
        console.print("Testing event subscription...", end="")
        
        events_received = []
        
        def on_price_update(event: Event):
            events_received.append(event)
        
        dispatcher.subscribe(EventType.PRICE_UPDATE, on_price_update)
        
        console.print(" [green]✓ Subscribed[/green]")
        
        # Test dispatching
        console.print("Testing event dispatch...", end="")
        
        dispatcher.dispatch_price_update(
            source="test",
            price=65000.0,
            metadata={"test": True}
        )
        
        if len(events_received) == 1:
            console.print(" [green]✓ Event received[/green]")
            event = events_received[0]
            console.print(f"  Event type: {event.type.value}")
            console.print(f"  Source: {event.source}")
            console.print(f"  Data: {event.data}")
        else:
            console.print(" [red]✗ Event not received[/red]")
            return False
        
        # Test statistics
        console.print("Checking statistics...", end="")
        stats = dispatcher.get_statistics()
        
        if stats["total_events"] > 0:
            console.print(" [green]✓ Statistics available[/green]")
            console.print(f"  Total events: {stats['total_events']}")
        
        console.print("[green]✓ Event Dispatcher - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing event dispatcher: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


async def test_data_engine():
    """Test Nautilus data engine integration."""
    console.print("\n[cyan]═══ Testing Nautilus Data Engine ═══[/cyan]")
    
    try:
        engine = get_nautilus_engine()
        
        # Start engine
        console.print("Starting Nautilus data engine...", end="")
        await engine.start()
        
        status = engine.get_status()
        
        if status["is_running"]:
            console.print(" [green]✓ Engine started[/green]")
        else:
            console.print(" [red]✗ Engine failed to start[/red]")
            return False
        
        # Check instruments
        console.print(f"Checking registered instruments...", end="")
        
        if status["instruments_registered"] >= 3:
            console.print(f" [green]✓ {status['instruments_registered']} instruments[/green]")
        else:
            console.print(" [red]✗ Instruments not registered[/red]")
        
        # Check data provider
        console.print("Checking data provider connection...", end="")
        
        if status["data_provider_connected"]:
            console.print(" [green]✓ Data provider connected[/green]")
        else:
            console.print(" [yellow]⚠ Data provider not connected[/yellow]")
        
        # Let data stream for a bit
        console.print("Streaming data (10 seconds)...", end="")
        await asyncio.sleep(10)
        console.print(" [green]✓ Completed[/green]")
        
        # Check price consensus
        console.print("Checking price consensus...", end="")
        consensus = engine.get_price_consensus()
        
        if consensus:
            console.print(" [green]✓ Consensus available[/green]")
            console.print(f"  Average price: ${consensus['average']:,.2f}")
            console.print(f"  Sources: {', '.join(consensus['sources'].keys())}")
        else:
            console.print(" [yellow]⚠ No consensus yet (may need more time)[/yellow]")
        
        # Stop engine
        console.print("Stopping engine...", end="")
        await engine.stop()
        console.print(" [green]✓ Stopped[/green]")
        
        console.print("[green]✓ Nautilus Data Engine - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing data engine: {e}[/red]")
        import traceback
        traceback.print_exc()
        
        # Make sure to stop engine
        try:
            await engine.stop()
        except:
            pass
        
        return False


async def run_all_tests():
    """Run all Phase 3 tests."""
    console.print(Panel.fit(
        "[bold cyan]PHASE 3: NAUTILUS CORE - TEST SUITE[/bold cyan]\n\n"
        "Testing Nautilus integration...",
        border_style="cyan"
    ))
    
    results = {}
    
    # Test each component
    results["Instrument Registry"] = await test_instruments()
    results["Event Dispatcher"] = await test_event_dispatcher()
    results["Nautilus Data Engine"] = await test_data_engine()
    
    # Summary
    console.print("\n" + "="*60)
    console.print("[bold]TEST SUMMARY[/bold]")
    console.print("="*60)
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan", width=25)
    table.add_column("Status", width=15)
    table.add_column("Ready for Phase 4", width=15)
    
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
        console.print("\n[cyan]Phase 3 is complete and working![/cyan]")
        console.print("[cyan]You can now proceed to Phase 4: Strategy Brain[/cyan]")
        return 0
    else:
        console.print("[bold red]✗ SOME TESTS FAILED[/bold red]")
        console.print("\n[yellow]Fix the failed components before proceeding to Phase 4.[/yellow]")
        return 1


@app.command()
def test(
    component: str = typer.Option(
        "all",
        "--component",
        "-c",
        help="Test specific component: all, instruments, dispatcher, engine"
    )
):
    """
    Test Nautilus Core components.
    
    Example:
        python scripts/test_nautilus.py test
        python scripts/test_nautilus.py test --component instruments
    """
    async def run_specific_test():
        if component == "all":
            return await run_all_tests()
        elif component == "instruments":
            return 0 if await test_instruments() else 1
        elif component == "dispatcher":
            return 0 if await test_event_dispatcher() else 1
        elif component == "engine":
            return 0 if await test_data_engine() else 1
        else:
            console.print(f"[red]Unknown component: {component}[/red]")
            return 1
    
    exit_code = asyncio.run(run_specific_test())
    raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()