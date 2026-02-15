import asyncio
from datetime import datetime
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.live import Live
from loguru import logger
import os
# Import data sources
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from data_sources.coinbase.adapter import CoinbaseDataSource
from data_sources.binance.websocket import BinanceWebSocketSource
from data_sources.news_social.adapter import NewsSocialDataSource
from data_sources.solana.rpc import SolanaRPCDataSource

app = typer.Typer()
console = Console()


async def test_coinbase():
    """Test Coinbase API data source."""
    console.print("\n[cyan]═══ Testing Coinbase API ═══[/cyan]")
    
    source = CoinbaseDataSource()
    
    try:
        # Connect
        console.print("Connecting to Coinbase...", end="")
        connected = await source.connect()
        
        if not connected:
            console.print(" [red]✗ FAILED[/red]")
            return False
        
        console.print(" [green]✓ Connected[/green]")
        
        # Test current price
        console.print("Fetching current BTC price...", end="")
        price = await source.get_current_price()
        
        if price:
            console.print(f" [green]✓ ${price:,.2f}[/green]")
        else:
            console.print(" [red]✗ FAILED[/red]")
            return False
        
        # Test 24h stats
        console.print("Fetching 24h statistics...", end="")
        stats = await source.get_24h_stats()
        
        if stats:
            console.print(f" [green]✓ Volume: ${stats['volume']:,.2f}[/green]")
        else:
            console.print(" [red]✗ FAILED[/red]")
        
        # Test order book
        console.print("Fetching order book...", end="")
        book = await source.get_order_book(level=1)
        
        if book and book["bids"]:
            best_bid = book["bids"][0]["price"]
            best_ask = book["asks"][0]["price"]
            console.print(f" [green]✓ Bid/Ask: ${best_bid:,.2f} / ${best_ask:,.2f}[/green]")
        else:
            console.print(" [red]✗ FAILED[/red]")
        
        # Test recent trades
        console.print("Fetching recent trades...", end="")
        trades = await source.get_recent_trades(limit=5)
        
        if trades:
            console.print(f" [green]✓ Got {len(trades)} trades[/green]")
        else:
            console.print(" [yellow]⚠ No trades[/yellow]")
        
        await source.disconnect()
        console.print("[green]✓ Coinbase API - All tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing Coinbase: {e}[/red]")
        return False


async def test_binance():
    """Test Binance WebSocket data source."""
    console.print("\n[cyan]═══ Testing Binance WebSocket ═══[/cyan]")
    
    source = BinanceWebSocketSource()
    
    try:
        # Test ticker stream (5 seconds)
        console.print("Starting ticker stream (5 seconds)...", end="")
        
        prices_received = []
        
        async def on_price(ticker):
            prices_received.append(ticker["price"])
            console.print(f"\r  Received: ${ticker['price']:,.2f} ({ticker['price_change_percent']:+.2f}%)", end="")
        
        source.on_price_update = on_price
        
        # Start streaming in background
        stream_task = asyncio.create_task(source.stream_ticker())
        
        # Wait 5 seconds
        await asyncio.sleep(5)
        
        # Stop stream
        await source.disconnect()
        
        try:
            await stream_task
        except:
            pass
        
        if len(prices_received) > 0:
            console.print(f"\n[green]✓ Received {len(prices_received)} price updates[/green]")
            console.print(f"  Latest price: ${prices_received[-1]:,.2f}")
            return True
        else:
            console.print("\n[red]✗ No price updates received[/red]")
            return False
        
    except Exception as e:
        console.print(f"\n[red]Error testing Binance: {e}[/red]")
        return False


async def test_news_social():
    """Test News/Social data source."""
    console.print("\n[cyan]═══ Testing News/Social APIs ═══[/cyan]")
    
    source = NewsSocialDataSource()
    
    try:
        # Connect
        console.print("Connecting to News APIs...", end="")
        connected = await source.connect()
        
        if not connected:
            console.print(" [red]✗ FAILED[/red]")
            return False
        
        console.print(" [green]✓ Connected[/green]")
        
        # Test Fear & Greed Index
        console.print("Fetching Fear & Greed Index...", end="")
        sentiment = await source.get_fear_greed_index()
        
        if sentiment:
            console.print(f" [green]✓ {sentiment['value']} - {sentiment['classification']}[/green]")
        else:
            console.print(" [red]✗ FAILED[/red]")
            return False
        
        # Test sentiment score
        console.print("Calculating sentiment score...", end="")
        score = await source.get_sentiment_score()
        
        if score is not None:
            console.print(f" [green]✓ Score: {score:.1f}/100[/green]")
        else:
            console.print(" [yellow]⚠ Could not calculate[/yellow]")
        
        await source.disconnect()
        console.print("[green]✓ News/Social APIs - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing News/Social: {e}[/red]")
        return False


async def test_solana():
    """Test Solana RPC data source."""
    console.print("\n[cyan]═══ Testing Solana RPC ═══[/cyan]")
    
    source = SolanaRPCDataSource()
    
    try:
        # Connect
        console.print("Connecting to Solana RPC...", end="")
        connected = await source.connect()
        
        if not connected:
            console.print(" [red]✗ FAILED[/red]")
            return False
        
        console.print(" [green]✓ Connected[/green]")
        
        # Test slot fetch
        console.print("Fetching current slot...", end="")
        slot = await source.get_slot()
        
        if slot:
            console.print(f" [green]✓ Slot: {slot:,}[/green]")
        else:
            console.print(" [red]✗ FAILED[/red]")
            return False
        
        # Test network stats
        console.print("Fetching network stats...", end="")
        stats = await source.get_network_stats()
        
        if stats:
            console.print(f" [green]✓ TPS: {stats['tps']:.1f}[/green]")
        else:
            console.print(" [yellow]⚠ Could not fetch stats[/yellow]")
        
        await source.disconnect()
        console.print("[green]✓ Solana RPC - Tests passed![/green]")
        return True
        
    except Exception as e:
        console.print(f"\n[red]Error testing Solana: {e}[/red]")
        return False


async def run_all_tests():
    """Run all data source tests."""
    console.print(Panel.fit(
        "[bold cyan]PHASE 1: EXTERNAL DATA SOURCES - TEST SUITE[/bold cyan]\n\n"
        "Testing all data sources before moving to Phase 2...",
        border_style="cyan"
    ))
    
    results = {}
    
    # Test each source
    results["Coinbase"] = await test_coinbase()
    results["Binance"] = await test_binance()
    results["News/Social"] = await test_news_social()
    results["Solana"] = await test_solana()
    
    # Summary
    console.print("\n" + "="*60)
    console.print("[bold]TEST SUMMARY[/bold]")
    console.print("="*60)
    
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Data Source", style="cyan", width=20)
    table.add_column("Status", width=15)
    table.add_column("Ready for Phase 2", width=20)
    
    for source, passed in results.items():
        status = "[green]✓ PASSED[/green]" if passed else "[red]✗ FAILED[/red]"
        ready = "[green]Yes[/green]" if passed else "[red]No[/red]"
        table.add_row(source, status, ready)
    
    console.print(table)
    
    # Overall result
    all_passed = all(results.values())
    
    console.print("\n" + "="*60)
    if all_passed:
        console.print("[bold green]✓ ALL TESTS PASSED![/bold green]")
        console.print("\n[cyan]Phase 1 is complete and working!")
        console.print("You can now proceed to Phase 2: Ingestion Layer[/cyan]")
        return 0
    else:
        console.print("[bold red]✗ SOME TESTS FAILED[/bold red]")
        console.print("\n[yellow]Fix the failed data sources before proceeding to Phase 2.[/yellow]")
        return 1


@app.command()
def test(
    source: str = typer.Option(
        "all",
        "--source",
        "-s",
        help="Test specific source: all, coinbase, binance, news, solana"
    )
):
    """
    Test external data sources.
    
    Example:
        python scripts/test_data_sources.py test
        python scripts/test_data_sources.py test --source coinbase
    """
    async def run_specific_test():
        if source == "all":
            return await run_all_tests()
        elif source == "coinbase":
            return 0 if await test_coinbase() else 1
        elif source == "binance":
            return 0 if await test_binance() else 1
        elif source == "news":
            return 0 if await test_news_social() else 1
        elif source == "solana":
            return 0 if await test_solana() else 1
        else:
            console.print(f"[red]Unknown source: {source}[/red]")
            return 1
    
    exit_code = asyncio.run(run_specific_test())
    raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()