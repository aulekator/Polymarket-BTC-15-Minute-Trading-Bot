#!/usr/bin/env python3
"""
Test Script for Phase 5: Execution Layer

Tests:
1. Risk Engine
2. Execution Engine
3. Order Placement and Fills
4. Position Management
5. Stop Loss / Take Profit

Run this after Phase 4 tests pass.
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

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from execution.risk_engine import get_risk_engine, RiskLimits
from execution.execution_engine import get_execution_engine
from execution.polymarket_client import get_polymarket_client
from core.strategy_brain.signal_processors.base_processor import SignalDirection

app = typer.Typer()
console = Console()


async def test_risk_engine():
    """Test risk management engine."""
    console.print("\n[cyan]═══ Testing Risk Engine ═══[/cyan]")
    
    try:
        risk = get_risk_engine()
        
        # Test position validation
        console.print("Testing position validation...", end="")
        
        # Valid position
        is_valid, error = risk.validate_new_position(
            size=Decimal("50.0"),
            direction="long",
            current_price=Decimal("65000"),
        )
        
        if is_valid:
            console.print(" [green]✓ Valid position accepted[/green]")
        else:
            console.print(f" [red]✗ Unexpected rejection: {error}[/red]")
            return False
        
        # Invalid position (too large)
        is_valid, error = risk.validate_new_position(
            size=Decimal("500.0"),  # Exceeds max
            direction="long",
            current_price=Decimal("65000"),
        )
        
        if not is_valid:
            console.print(f" [green]✓ Oversized position rejected: {error}[/green]")
        else:
            console.print(" [red]✗ Should have rejected oversized position[/red]")
            return False
        
        # Test position size calculation
        console.print("\nTesting position size calculation...", end="")
        
        size = risk.calculate_position_size(
            signal_confidence=0.80,
            signal_score=75.0,
            current_price=Decimal("65000"),
        )
        
        if size > 0:
            console.print(f" [green]✓ Calculated size: ${size:.2f}[/green]")
        else:
            console.print(" [red]✗ Invalid position size[/red]")
            return False
        
        # Test position tracking
        console.print("\nTesting position tracking...", end="")
        
        risk.add_position(
            position_id="test_pos_1",
            size=Decimal("50.0"),
            entry_price=Decimal("65000"),
            direction="long",
            stop_loss=Decimal("58500"),  # -10%
            take_profit=Decimal("71500"),  # +10%
        )
        
        console.print(" [green]✓ Position added[/green]")
        
        # Update position with new price
        risk_pos = risk.update_position("test_pos_1", Decimal("67000"))
        
        if risk_pos and risk_pos.unrealized_pnl > 0:
            console.print(f"  Unrealized P&L: ${risk_pos.unrealized_pnl:+.2f}")
            console.print(f"  Risk Level: {risk_pos.risk_level.value}")
        
        # Get risk summary
        console.print("\nGetting risk summary...", end="")
        summary = risk.get_risk_summary()
        
        console.print(" [green]✓ Summary generated[/green]")
        console.print(f"  Positions: {summary['positions']['count']}")
        console.print(f"  Exposure: ${summary['exposure']['current']:.2f}")
        console.print(f"  Unrealized P&L: ${summary['pnl']['unrealized']:.2f}")
        
        console.print("\n[green]✓ Risk Engine - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing risk engine: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


async def test_execution_engine():
    """Test execution engine."""
    console.print("\n[cyan]═══ Testing Execution Engine ═══[/cyan]")
    
    try:
        execution = get_execution_engine()
        
        # Test signal execution
        console.print("Executing bullish signal...", end="")
        
        order = await execution.execute_signal(
            signal_direction=SignalDirection.BULLISH,
            signal_confidence=0.75,
            signal_score=80.0,
            current_price=Decimal("65000"),
            stop_loss=Decimal("58500"),
            take_profit=Decimal("71500"),
        )
        
        if order:
            console.print(" [green]✓ Order created[/green]")
            console.print(f"  Order ID: {order.order_id}")
            console.print(f"  Size: ${order.size:.2f}")
            console.print(f"  Status: {order.status.value}")
        else:
            console.print(" [red]✗ Order creation failed[/red]")
            return False
        
        # Check position opened
        console.print("\nChecking position opened...", end="")
        
        await asyncio.sleep(1)  # Give time for callbacks
        
        positions = execution.get_open_positions()
        
        if len(positions) > 0:
            console.print(f" [green]✓ {len(positions)} position(s) open[/green]")
            pos = positions[0]
            console.print(f"  Position ID: {pos['position_id']}")
            console.print(f"  Direction: {pos['direction']}")
            console.print(f"  Entry: ${pos['entry_price']:,.2f}")
        else:
            console.print(" [yellow]⚠ No positions opened[/yellow]")
        
        # Test position update
        console.print("\nUpdating positions with new price...", end="")
        
        await execution.update_positions(Decimal("67000"))
        
        console.print(" [green]✓ Positions updated[/green]")
        
        # Test position close
        if positions:
            console.print("\nClosing position...", end="")
            
            pnl = await execution.close_position(
                position_id=positions[0]["position_id"],
                exit_price=Decimal("67000"),
                reason="test_exit",
            )
            
            if pnl is not None:
                console.print(f" [green]✓ Position closed (P&L: ${pnl:+.2f})[/green]")
            else:
                console.print(" [red]✗ Failed to close position[/red]")
        
        # Get statistics
        console.print("\nGetting execution statistics...", end="")
        stats = execution.get_statistics()
        
        console.print(" [green]✓ Stats available[/green]")
        console.print(f"  Total orders: {stats['orders']['total']}")
        console.print(f"  Filled orders: {stats['orders']['filled']}")
        console.print(f"  Open positions: {stats['positions']['open']}")
        
        console.print("\n[green]✓ Execution Engine - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing execution engine: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


async def test_polymarket_client():
    """Test Polymarket client placeholder."""
    console.print("\n[cyan]═══ Testing Polymarket Client ═══[/cyan]")
    
    try:
        client = get_polymarket_client()
        
        # Test connection
        console.print("Connecting to Polymarket...", end="")
        connected = await client.connect()
        
        if connected:
            console.print(" [green]✓ Connected (placeholder)[/green]")
        else:
            console.print(" [red]✗ Connection failed[/red]")
            return False
        
        # Test price fetch
        console.print("Fetching market price...", end="")
        price = await client.get_market_price("btc_market_test")
        
        if price:
            console.print(f" [green]✓ Price: {price:.4f}[/green]")
        
        # Test balance
        console.print("Getting balance...", end="")
        balance = await client.get_balance()
        
        if balance:
            console.print(f" [green]✓ USDC: ${balance['USDC']:,.2f}[/green]")
        
        await client.disconnect()
        
        console.print("\n[green]✓ Polymarket Client - Tests passed![/green]")
        console.print("[yellow]Note: This is a placeholder. Real Polymarket integration requires API setup.[/yellow]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing Polymarket client: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """Run all Phase 5 tests."""
    console.print(Panel.fit(
        "[bold cyan]PHASE 5: EXECUTION LAYER - TEST SUITE[/bold cyan]\n\n"
        "Testing order execution and position management...",
        border_style="cyan"
    ))
    
    results = {}
    
    # Test each component
    results["Risk Engine"] = await test_risk_engine()
    results["Execution Engine"] = await test_execution_engine()
    results["Polymarket Client"] = await test_polymarket_client()
    
    # Summary
    console.print("\n" + "="*60)
    console.print("[bold]TEST SUMMARY[/bold]")
    console.print("="*60)
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Component", style="cyan", width=25)
    table.add_column("Status", width=15)
    table.add_column("Ready for Phase 6", width=15)
    
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
        console.print("\n[cyan]Phase 5 is complete and working![/cyan]")
        console.print("[cyan]You can now proceed to Phase 6: Monitoring & Analytics[/cyan]")
        return 0
    else:
        console.print("[bold red]✗ SOME TESTS FAILED[/bold red]")
        console.print("\n[yellow]Fix the failed components before proceeding to Phase 6.[/yellow]")
        return 1


@app.command()
def test(
    component: str = typer.Option(
        "all",
        "--component",
        "-c",
        help="Test specific component: all, risk, execution, polymarket"
    )
):
    """
    Test Execution Layer components.
    
    Example:
        python scripts/test_execution.py test
        python scripts/test_execution.py test --component risk
    """
    async def run_specific_test():
        if component == "all":
            return await run_all_tests()
        elif component == "risk":
            return 0 if await test_risk_engine() else 1
        elif component == "execution":
            return 0 if await test_execution_engine() else 1
        elif component == "polymarket":
            return 0 if await test_polymarket_client() else 1
        else:
            console.print(f"[red]Unknown component: {component}[/red]")
            return 1
    
    exit_code = asyncio.run(run_specific_test())
    raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()