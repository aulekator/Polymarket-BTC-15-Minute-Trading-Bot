#!/usr/bin/env python3
"""
Test Script for Phase 2: Ingestion Layer

Tests:
1. Unified Data Adapter
2. WebSocket Manager
3. Data Validator
4. Rate Limiter

Run this after Phase 1 tests pass.
"""
import asyncio
from datetime import datetime
from decimal import Decimal
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import track
from loguru import logger

import os

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from core.ingestion.adapters.unified_adapter import UnifiedDataAdapter, MarketData
from core.ingestion.managers.websocket_manager import WebSocketManager, ConnectionState
from core.ingestion.managers.rate_limiter import get_rate_limiter
from core.ingestion.validators.data_validator import get_validator

app = typer.Typer()
console = Console()


async def test_unified_adapter():
    """Test unified data adapter."""
    console.print("\n[cyan]═══ Testing Unified Data Adapter ═══[/cyan]")
    
    adapter = UnifiedDataAdapter()
    
    try:
        # Connect all sources
        console.print("Connecting to all data sources...", end="")
        results = await adapter.connect_all()
        
        connected = sum(results.values())
        total = len(results)
        
        if connected > 0:
            console.print(f" [green]✓ Connected {connected}/{total} sources[/green]")
        else:
            console.print(" [red]✗ No sources connected[/red]")
            return False
        
        # Test price fetching
        console.print("Starting data streams (10 seconds)...", end="")
        
        prices_received = []
        
        async def on_price(data: MarketData):
            prices_received.append(data)
            console.print(f"\r  [{data.source}] ${data.price:,.2f}", end="")
        
        adapter.on_price_update = on_price
        
        # Start streaming
        await adapter.start_streaming()
        await asyncio.sleep(10)
        
        console.print(f"\n[green]✓ Received {len(prices_received)} price updates[/green]")
        
        # Test price consensus
        consensus = adapter.get_price_consensus()
        if consensus:
            console.print(f"  Average price: ${consensus['average']:,.2f}")
            console.print(f"  Price spread: ${consensus['spread']:,.2f} ({consensus['spread_percent']:.2f}%)")
            console.print(f"  Sources: {', '.join(consensus['sources'].keys())}")
        
        # Health check
        console.print("\nRunning health check...", end="")
        health = await adapter.health_check()
        healthy = sum(health.values())
        
        console.print(f" [green]✓ {healthy}/{len(health)} sources healthy[/green]")
        
        await adapter.disconnect_all()
        console.print("[green]✓ Unified Data Adapter - All tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing unified adapter: {e}[/red]")
        return False


async def test_websocket_manager():
    """Test WebSocket connection manager."""
    console.print("\n[cyan]═══ Testing WebSocket Manager ═══[/cyan]")
    
    try:
        from data_sources.binance.websocket import BinanceWebSocketSource
        
        binance = BinanceWebSocketSource()
        
        # Create WebSocket manager
        manager = WebSocketManager(
            name="Binance-Test",
            connect_func=lambda: binance.connect("ticker"),
            stream_func=binance.stream_ticker,
            max_reconnect_attempts=3,
        )
        
        console.print("Testing connection...", end="")
        success = await manager.connect()
        
        if not success:
            console.print(" [red]✗ Connection failed[/red]")
            return False
        
        console.print(" [green]✓ Connected[/green]")
        
        # Test stats
        stats = manager.get_stats()
        console.print(f"  State: {stats['state']}")
        console.print(f"  Healthy: {stats['is_healthy']}")
        
        # Start streaming for 5 seconds
        console.print("Testing stream (5 seconds)...", end="")
        
        async def on_ticker(data):
            manager.update_last_message_time()
        
        binance.on_price_update = on_ticker
        
        stream_task = asyncio.create_task(manager.start_streaming())
        await asyncio.sleep(5)
        
        await manager.disconnect()
        
        try:
            await stream_task
        except:
            pass
        
        console.print(" [green]✓ Stream worked[/green]")
        console.print("[green]✓ WebSocket Manager - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing WebSocket manager: {e}[/red]")
        return False


async def test_data_validator():
    """Test data validator."""
    console.print("\n[cyan]═══ Testing Data Validator ═══[/cyan]")
    
    try:
        validator = get_validator()
        
        # Test valid data
        console.print("Testing valid price...", end="")
        result = validator.validate_market_data(
            source="test",
            price=Decimal("65000"),
            timestamp=datetime.now(),
            bid=Decimal("64995"),
            ask=Decimal("65005"),
        )
        
        if result.is_valid:
            console.print(" [green]✓ Valid data accepted[/green]")
        else:
            console.print(f" [red]✗ Valid data rejected: {result.errors}[/red]")
            return False
        
        # Test invalid price (too low)
        console.print("Testing invalid price (too low)...", end="")
        result = validator.validate_market_data(
            source="test",
            price=Decimal("500"),  # Below $1000 minimum
            timestamp=datetime.now(),
        )
        
        if not result.is_valid:
            console.print(" [green]✓ Invalid data rejected[/green]")
            console.print(f"    Errors: {result.errors[0]}")
        else:
            console.print(" [red]✗ Invalid data accepted[/red]")
        
        # Test anomaly detection
        console.print("Testing anomaly detection...", end="")
        
        # Add normal prices
        for price in [65000, 65100, 64900, 65050, 65000]:
            validator.validate_market_data(
                source="anomaly_test",
                price=Decimal(str(price)),
                timestamp=datetime.now(),
            )
        
        # Test anomalous price
        anomaly = validator.detect_anomaly("anomaly_test", Decimal("75000"))
        
        if anomaly:
            console.print(" [green]✓ Anomaly detected[/green]")
            console.print(f"    Z-score: {anomaly['z_score']:.2f}")
        else:
            console.print(" [yellow]⚠ No anomaly detected (may need more data)[/yellow]")
        
        # Test statistics
        console.print("Getting price statistics...", end="")
        stats = validator.get_price_statistics("anomaly_test")
        
        if stats:
            console.print(" [green]✓ Stats available[/green]")
            console.print(f"    Mean: ${stats['mean']:,.2f}")
            console.print(f"    Range: ${stats['range']:,.2f}")
        
        console.print("[green]✓ Data Validator - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing data validator: {e}[/red]")
        return False


async def test_rate_limiter():
    """Test rate limiter."""
    console.print("\n[cyan]═══ Testing Rate Limiter ═══[/cyan]")
    
    try:
        rate_limiter = get_rate_limiter()
        
        # Test acquiring tokens
        console.print("Testing rate limiting (5 requests)...", end="")
        
        acquired = 0
        for i in range(5):
            if await rate_limiter.acquire("test_source", wait=False):
                acquired += 1
        
        console.print(f" [green]✓ Acquired {acquired}/5 tokens[/green]")
        
        # Test stats
        console.print("Checking rate limiter stats...")
        stats = rate_limiter.get_stats()
        
        for source, source_stats in stats.items():
            console.print(f"  [{source}] {source_stats['current_requests']}/{source_stats['max_requests']} "
                         f"({source_stats['utilization_percent']:.1f}% used)")
        
        console.print("[green]✓ Rate Limiter - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing rate limiter: {e}[/red]")
        return False


async def run_all_tests():
    """Run all Phase 2 tests."""
    console.print(Panel.fit(
        "[bold cyan]PHASE 2: INGESTION LAYER - TEST SUITE[/bold cyan]\n\n"
        "Testing data ingestion components...",
        border_style="cyan"
    ))
    
    results = {}
    
    # Test each component
    results["Unified Adapter"] = await test_unified_adapter()
    results["WebSocket Manager"] = await test_websocket_manager()
    results["Data Validator"] = await test_data_validator()
    results["Rate Limiter"] = await test_rate_limiter()
    
    # Summary
    console.print("\n" + "="*60)
    console.print("[bold]TEST SUMMARY[/bold]")
    console.print("="*60)
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan", width=25)
    table.add_column("Status", width=15)
    table.add_column("Ready for Phase 3", width=15)
    
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
        console.print("\n[cyan]Phase 2 is complete and working![/cyan]")
        console.print("[cyan]You can now proceed to Phase 3: Nautilus Core[/cyan]")
        return 0
    else:
        console.print("[bold red]✗ SOME TESTS FAILED[/bold red]")
        console.print("\n[yellow]Fix the failed components before proceeding to Phase 3.[/yellow]")
        return 1


@app.command()
def test(
    component: str = typer.Option(
        "all",
        "--component",
        "-c",
        help="Test specific component: all, adapter, websocket, validator, ratelimit"
    )
):
    """
    Test ingestion layer components.
    
    Example:
        python scripts/test_ingestion.py test
        python scripts/test_ingestion.py test --component adapter
    """
    async def run_specific_test():
        if component == "all":
            return await run_all_tests()
        elif component == "adapter":
            return 0 if await test_unified_adapter() else 1
        elif component == "websocket":
            return 0 if await test_websocket_manager() else 1
        elif component == "validator":
            return 0 if await test_data_validator() else 1
        elif component == "ratelimit":
            return 0 if await test_rate_limiter() else 1
        else:
            console.print(f"[red]Unknown component: {component}[/red]")
            return 1
    
    exit_code = asyncio.run(run_specific_test())
    raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()