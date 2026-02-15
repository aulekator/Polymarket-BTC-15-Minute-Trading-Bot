"""
Paper Trading Viewer
View and analyze simulation trades
"""
import json
from datetime import datetime
from pathlib import Path


def load_paper_trades():
    """Load paper trades from file."""
    try:
        with open('paper_trades.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("No paper trades file found.")
        return []
    except Exception as e:
        print(f"Error loading paper trades: {e}")
        return []


def display_paper_trades(trades):
    """Display paper trades in a nice format."""
    if not trades:
        print("\nNo paper trades recorded yet.")
        return
    
    print("\n" + "=" * 100)
    print("PAPER TRADING RESULTS (SIMULATION)")
    print("=" * 100)
    print()
    
    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if t.get('outcome') == 'WIN')
    losing_trades = sum(1 for t in trades if t.get('outcome') == 'LOSS')
    pending_trades = sum(1 for t in trades if t.get('outcome') == 'PENDING')
    
    print(f"Total Trades: {total_trades}")
    print(f"Winning: {winning_trades}")
    print(f"Losing: {losing_trades}")
    print(f"Pending: {pending_trades}")
    
    if winning_trades + losing_trades > 0:
        win_rate = winning_trades / (winning_trades + losing_trades) * 100
        print(f"Win Rate: {win_rate:.1f}%")
    
    print()
    print("-" * 100)
    print(f"{'#':<4} {'Time':<20} {'Direction':<10} {'Size':<12} {'Price':<12} {'Score':<8} {'Confidence':<12} {'Outcome':<10}")
    print("-" * 100)
    
    for i, trade in enumerate(trades, 1):
        timestamp = datetime.fromisoformat(trade['timestamp']).strftime('%Y-%m-%d %H:%M')
        direction = trade['direction']
        size = f"${trade['size_usd']:.2f}"
        price = f"${trade['price']:,.2f}"
        score = f"{trade['signal_score']:.1f}"
        confidence = f"{trade['signal_confidence']:.1%}"
        outcome = trade.get('outcome', 'PENDING')
        
        print(f"{i:<4} {timestamp:<20} {direction:<10} {size:<12} {price:<12} {score:<8} {confidence:<12} {outcome:<10}")
    
    print("-" * 100)
    print()


def main():
    """Main entry point."""
    trades = load_paper_trades()
    display_paper_trades(trades)
    
    if trades:
        print("\nNOTE: These are SIMULATION trades only - no real money involved!")
        print("To update outcomes, edit paper_trades.json manually")
        print()


if __name__ == "__main__":
    main()