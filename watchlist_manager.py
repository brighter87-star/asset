"""
Watchlist Manager - Add/remove items from watchlist with auto-dating.

Usage:
    python watchlist_manager.py add 005930 85000 --max-units 2    # Add Samsung @ 85,000원
    python watchlist_manager.py add 삼성전자 85000                 # Add by name
    python watchlist_manager.py remove 005930                      # Remove by ticker
    python watchlist_manager.py update 005930 --target 90000       # Update target price
    python watchlist_manager.py list                               # List all items
"""

import argparse
import pandas as pd
from datetime import date
from pathlib import Path

from services.kiwoom_service import get_stock_code, get_stock_name

WATCHLIST_PATH = Path(__file__).parent / "watchlist.csv"


def load_watchlist() -> pd.DataFrame:
    """Load watchlist from CSV."""
    if WATCHLIST_PATH.exists():
        df = pd.read_csv(WATCHLIST_PATH)
        # Ensure ticker is string and zero-padded
        if "ticker" in df.columns:
            df["ticker"] = df["ticker"].astype(str).str.zfill(6)
        return df
    return pd.DataFrame(columns=["ticker", "name", "target_price", "stop_loss_pct", "max_units", "added_date"])


def save_watchlist(df: pd.DataFrame):
    """Save watchlist to CSV."""
    df.to_csv(WATCHLIST_PATH, index=False)


def resolve_ticker_and_name(ticker_or_name: str) -> tuple:
    """
    Resolve ticker and name from input.
    Input can be:
    - 6-digit ticker (e.g., "005930")
    - Stock name (e.g., "삼성전자")

    Returns (ticker, name) tuple.
    """
    input_str = ticker_or_name.strip()

    # Check if it's a 6-digit ticker
    if input_str.isdigit() and len(input_str) <= 6:
        ticker = input_str.zfill(6)
        name = get_stock_name(ticker)
        if not name:
            print(f"[WARN] Could not find name for ticker {ticker}")
        return ticker, name

    # Otherwise treat as name
    ticker = get_stock_code(input_str)
    if not ticker:
        print(f"[ERROR] Could not find ticker for '{input_str}'")
        return None, None

    name = input_str
    return ticker, name


def add_item(ticker_or_name: str, target_price: int, max_units: int = 1, stop_loss_pct: float = None):
    """Add item to watchlist with auto-dated added_date."""
    df = load_watchlist()

    ticker, name = resolve_ticker_and_name(ticker_or_name)
    if not ticker:
        return

    # Check if already exists
    if ticker in df["ticker"].values:
        print(f"[WARN] {name} ({ticker}) already in watchlist. Use 'update' to modify.")
        return

    new_row = {
        "ticker": ticker,
        "name": name,
        "target_price": target_price,
        "stop_loss_pct": stop_loss_pct if stop_loss_pct else "",
        "max_units": max_units,
        "added_date": str(date.today()),
    }

    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_watchlist(df)
    print(f"[OK] Added {name} ({ticker}) @ {target_price:,}원 (max_units={max_units}, added={date.today()})")


def remove_item(ticker_or_name: str):
    """Remove item from watchlist."""
    df = load_watchlist()

    ticker, name = resolve_ticker_and_name(ticker_or_name)
    if not ticker:
        # Try direct match if resolve failed
        ticker = ticker_or_name.strip().zfill(6) if ticker_or_name.strip().isdigit() else None
        if not ticker:
            return

    if ticker not in df["ticker"].values:
        print(f"[WARN] {ticker} not in watchlist.")
        return

    removed_name = df[df["ticker"] == ticker]["name"].values[0]
    df = df[df["ticker"] != ticker]
    save_watchlist(df)
    print(f"[OK] Removed {removed_name} ({ticker}) from watchlist")


def update_item(ticker_or_name: str, target_price: int = None, max_units: int = None, stop_loss_pct: float = None):
    """Update existing item in watchlist."""
    df = load_watchlist()

    ticker, name = resolve_ticker_and_name(ticker_or_name)
    if not ticker:
        return

    if ticker not in df["ticker"].values:
        print(f"[WARN] {ticker} not in watchlist. Use 'add' to create.")
        return

    idx = df[df["ticker"] == ticker].index[0]

    if target_price is not None:
        df.loc[idx, "target_price"] = target_price
    if max_units is not None:
        df.loc[idx, "max_units"] = max_units
    if stop_loss_pct is not None:
        df.loc[idx, "stop_loss_pct"] = stop_loss_pct

    save_watchlist(df)
    updated_name = df.loc[idx, "name"]
    print(f"[OK] Updated {updated_name} ({ticker})")


def list_items():
    """List all items in watchlist."""
    df = load_watchlist()

    if df.empty:
        print("Watchlist is empty.")
        return

    print(f"\n{'Ticker':<8} {'Name':<14} {'Target':>12} {'Max':>5} {'SL%':>6} {'Added':>12}")
    print("-" * 62)

    for _, row in df.iterrows():
        ticker = row["ticker"]
        name = str(row.get("name", ""))[:12]  # Truncate long names
        target = int(row["target_price"])
        max_units = int(row.get("max_units", 1)) if pd.notna(row.get("max_units")) else 1
        sl = row.get("stop_loss_pct", "")
        sl_str = f"{sl:.1f}" if pd.notna(sl) and sl != "" else "-"
        added = row.get("added_date", "")
        added_str = str(added) if pd.notna(added) and added != "" else "-"

        print(f"{ticker:<8} {name:<14} {target:>12,} {max_units:>5} {sl_str:>6} {added_str:>12}")

    print("-" * 62)
    print(f"Total: {len(df)} items")


def main():
    parser = argparse.ArgumentParser(description="Manage watchlist items")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # add command
    add_parser = subparsers.add_parser("add", help="Add item to watchlist")
    add_parser.add_argument("ticker", type=str, help="Stock ticker (6-digit) or name (e.g., 005930 or 삼성전자)")
    add_parser.add_argument("target_price", type=int, help="Target price for breakout (원)")
    add_parser.add_argument("--max-units", type=int, default=1, help="Max units to buy (default: 1)")
    add_parser.add_argument("--stop-loss", type=float, help="Custom stop loss %")

    # remove command
    remove_parser = subparsers.add_parser("remove", help="Remove item from watchlist")
    remove_parser.add_argument("ticker", type=str, help="Stock ticker or name")

    # update command
    update_parser = subparsers.add_parser("update", help="Update item in watchlist")
    update_parser.add_argument("ticker", type=str, help="Stock ticker or name")
    update_parser.add_argument("--target", type=int, help="New target price (원)")
    update_parser.add_argument("--max-units", type=int, help="New max units")
    update_parser.add_argument("--stop-loss", type=float, help="New stop loss %")

    # list command
    subparsers.add_parser("list", help="List all items in watchlist")

    args = parser.parse_args()

    if args.command == "add":
        add_item(args.ticker, args.target_price, args.max_units, args.stop_loss)
    elif args.command == "remove":
        remove_item(args.ticker)
    elif args.command == "update":
        update_item(args.ticker, args.target, args.max_units, args.stop_loss)
    elif args.command == "list":
        list_items()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
