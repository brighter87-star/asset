"""
Watchlist Manager - Add/remove items from watchlist with auto-dating.

Usage:
    python watchlist_manager.py add 삼성전자 85000 --max-units 2    # Add by name
    python watchlist_manager.py add 005930 85000 --date 2/6         # Add with specific date
    python watchlist_manager.py add 삼성전자 85000 --date 2월6일    # Korean date format
    python watchlist_manager.py remove 삼성전자                       # Remove by name
    python watchlist_manager.py update 삼성전자 --target 90000       # Update target price (date auto-updates to today)
    python watchlist_manager.py update 삼성전자 --date 2/7           # Update date only (no auto-update)
    python watchlist_manager.py list                                 # List all items
"""

import argparse
import re
import pandas as pd
from datetime import date, datetime
from pathlib import Path

from services.kiwoom_service import get_stock_code, get_stock_name

WATCHLIST_PATH = Path(__file__).parent / "watchlist.csv"


def parse_flexible_date(date_str: str) -> date:
    """
    Parse date from various flexible formats.

    Supported formats:
    - 2/6, 02/6, 2/06, 02/06
    - 2-6, 02-6, 2-06, 02-06
    - 2.6, 02.6, 2.06, 02.06
    - 2월6일, 02월06일, 2월 6일
    - 2026-02-06 (ISO format)

    Returns date object. Year defaults to current year.
    """
    date_str = date_str.strip()
    current_year = date.today().year

    # ISO format: 2026-02-06
    if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', date_str):
        parts = date_str.split('-')
        return date(int(parts[0]), int(parts[1]), int(parts[2]))

    # Korean format: 2월6일, 02월 06일, etc.
    korean_match = re.match(r'^(\d{1,2})\s*월\s*(\d{1,2})\s*일?$', date_str)
    if korean_match:
        month = int(korean_match.group(1))
        day = int(korean_match.group(2))
        return date(current_year, month, day)

    # Slash format: 2/6, 02/06
    slash_match = re.match(r'^(\d{1,2})/(\d{1,2})$', date_str)
    if slash_match:
        month = int(slash_match.group(1))
        day = int(slash_match.group(2))
        return date(current_year, month, day)

    # Dash format: 2-6, 02-06
    dash_match = re.match(r'^(\d{1,2})-(\d{1,2})$', date_str)
    if dash_match:
        month = int(dash_match.group(1))
        day = int(dash_match.group(2))
        return date(current_year, month, day)

    # Dot format: 2.6, 02.06
    dot_match = re.match(r'^(\d{1,2})\.(\d{1,2})$', date_str)
    if dot_match:
        month = int(dot_match.group(1))
        day = int(dot_match.group(2))
        return date(current_year, month, day)

    raise ValueError(f"Cannot parse date: '{date_str}'. Use formats like 2/6, 2월6일, 02-06")


def get_display_width(text: str) -> int:
    """Calculate display width considering Korean characters (width 2)."""
    width = 0
    for char in text:
        if '\uac00' <= char <= '\ud7a3' or '\u3131' <= char <= '\u318e':
            width += 2  # Korean characters
        else:
            width += 1  # ASCII and others
    return width


def pad_korean(text: str, width: int, align: str = 'left') -> str:
    """Pad text to specified width considering Korean character width."""
    current_width = get_display_width(text)
    padding = width - current_width

    if padding <= 0:
        return text

    if align == 'left':
        return text + ' ' * padding
    elif align == 'right':
        return ' ' * padding + text
    else:  # center
        left_pad = padding // 2
        right_pad = padding - left_pad
        return ' ' * left_pad + text + ' ' * right_pad


def truncate_korean(text: str, max_width: int) -> str:
    """Truncate text to max display width."""
    width = 0
    result = ""
    for char in text:
        char_width = 2 if '\uac00' <= char <= '\ud7a3' or '\u3131' <= char <= '\u318e' else 1
        if width + char_width > max_width:
            break
        result += char
        width += char_width
    return result


def load_watchlist() -> pd.DataFrame:
    """Load watchlist from CSV."""
    if WATCHLIST_PATH.exists():
        return pd.read_csv(WATCHLIST_PATH)
    return pd.DataFrame(columns=["name", "target_price", "stop_loss_pct", "max_units", "added_date"])


def save_watchlist(df: pd.DataFrame):
    """Save watchlist to CSV."""
    df.to_csv(WATCHLIST_PATH, index=False)


def resolve_name(ticker_or_name: str) -> str:
    """
    Resolve stock name from input.
    Input can be:
    - 6-digit ticker (e.g., "005930") -> returns name
    - Stock name (e.g., "삼성전자") -> returns name as-is

    Returns name string or None if not found.
    """
    input_str = ticker_or_name.strip()

    # Check if it's a 6-digit ticker
    if input_str.isdigit() and len(input_str) <= 6:
        ticker = input_str.zfill(6)
        name = get_stock_name(ticker)
        if not name:
            print(f"[ERROR] Could not find name for ticker {ticker}")
            return None
        return name

    # Otherwise treat as name - verify it exists
    ticker = get_stock_code(input_str)
    if not ticker:
        print(f"[ERROR] Could not find stock '{input_str}'")
        return None

    return input_str


def add_item(ticker_or_name: str, target_price: int, max_units: int = 1, stop_loss_pct: float = None, added_date: date = None):
    """Add item to watchlist."""
    df = load_watchlist()

    name = resolve_name(ticker_or_name)
    if not name:
        return

    # Check if already exists
    if name in df["name"].values:
        existing = df[df["name"] == name].iloc[0]
        print(f"[WARN] {name} already in watchlist. Use 'update' to modify.")
        print(f"  Current settings:")
        print(f"    - Target price: {int(existing['target_price']):,}원")
        print(f"    - Max units: {int(existing['max_units'])}")
        if pd.notna(existing.get('stop_loss_pct')):
            print(f"    - Stop loss: {existing['stop_loss_pct']}%")
        print(f"    - Added: {existing.get('added_date', 'N/A')}")
        return

    effective_date = added_date if added_date else date.today()
    new_row = {
        "name": name,
        "target_price": target_price,
        "stop_loss_pct": stop_loss_pct if stop_loss_pct else "",
        "max_units": max_units,
        "added_date": str(effective_date),
    }

    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_watchlist(df)
    print(f"[OK] Added {name} @ {target_price:,}원 (max_units={max_units}, added={effective_date})")


def remove_item(ticker_or_name: str):
    """Remove item from watchlist."""
    df = load_watchlist()

    name = resolve_name(ticker_or_name)
    if not name:
        return

    if name not in df["name"].values:
        print(f"[WARN] {name} not in watchlist.")
        return

    df = df[df["name"] != name]
    save_watchlist(df)
    print(f"[OK] Removed {name} from watchlist")


def update_item(ticker_or_name: str, target_price: int = None, max_units: int = None, stop_loss_pct: float = None, added_date: date = None):
    """Update existing item in watchlist."""
    df = load_watchlist()

    name = resolve_name(ticker_or_name)
    if not name:
        return

    if name not in df["name"].values:
        print(f"[WARN] {name} not in watchlist. Use 'add' to create.")
        return

    idx = df[df["name"] == name].index[0]
    old_row = df.loc[idx].copy()

    # Track changes
    changes = []
    if target_price is not None:
        old_val = int(old_row["target_price"])
        df.loc[idx, "target_price"] = target_price
        changes.append(f"target: {old_val:,}원 → {target_price:,}원")
    if max_units is not None:
        old_val = int(old_row["max_units"])
        df.loc[idx, "max_units"] = max_units
        changes.append(f"max_units: {old_val} → {max_units}")
    if stop_loss_pct is not None:
        old_val = old_row.get("stop_loss_pct")
        old_str = f"{old_val}%" if pd.notna(old_val) else "default"
        df.loc[idx, "stop_loss_pct"] = stop_loss_pct
        changes.append(f"stop_loss: {old_str} → {stop_loss_pct}%")
    if added_date is not None:
        old_val = old_row.get("added_date", "N/A")
        df.loc[idx, "added_date"] = str(added_date)
        changes.append(f"added_date: {old_val} → {added_date}")

    if not changes:
        print(f"[WARN] No changes specified for {name}")
        print(f"  Current: target={int(old_row['target_price']):,}원, max_units={int(old_row['max_units'])}, added={old_row.get('added_date', 'N/A')}")
        return

    save_watchlist(df)
    print(f"[OK] Updated {name}")
    for change in changes:
        print(f"  {change}")


def get_item(ticker_or_name: str):
    """Get details of a specific item in watchlist."""
    df = load_watchlist()

    name = resolve_name(ticker_or_name)
    if not name:
        return

    if name not in df["name"].values:
        print(f"[NOT FOUND] {name} is not in watchlist")
        return

    row = df[df["name"] == name].iloc[0]
    ticker = get_stock_code(name)

    print(f"[FOUND] {name} ({ticker})")
    print(f"  - Target price: {int(row['target_price']):,}원")
    print(f"  - Max units: {int(row['max_units'])}")
    if pd.notna(row.get('stop_loss_pct')):
        print(f"  - Stop loss: {row['stop_loss_pct']}%")
    else:
        print(f"  - Stop loss: default")
    print(f"  - Added: {row.get('added_date', 'N/A')}")


def list_items():
    """List all items in watchlist."""
    df = load_watchlist()

    if df.empty:
        print("Watchlist is empty.")
        return

    print(f"\n{'Name':<14} {'Target':>12} {'Max':>5} {'SL%':>6} {'Added':>12}")
    print("-" * 54)

    for _, row in df.iterrows():
        name = str(row.get("name", ""))
        # Truncate to max display width of 12
        if get_display_width(name) > 12:
            name = truncate_korean(name, 12)
        # Pad to width 14 (left-aligned)
        name_display = pad_korean(name, 14, 'left')

        target = int(row["target_price"])
        max_units = int(row.get("max_units", 1)) if pd.notna(row.get("max_units")) else 1
        sl = row.get("stop_loss_pct", "")
        sl_str = f"{sl:.1f}" if pd.notna(sl) and sl != "" else "-"
        added = row.get("added_date", "")
        added_str = str(added) if pd.notna(added) and added != "" else "-"

        print(f"{name_display} {target:>12,} {max_units:>5} {sl_str:>6} {added_str:>12}")

    print("-" * 54)
    print(f"Total: {len(df)} items")


def main():
    parser = argparse.ArgumentParser(description="Manage watchlist items")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # add command
    add_parser = subparsers.add_parser("add", help="Add item to watchlist")
    add_parser.add_argument("name", type=str, help="Stock name or ticker (e.g., 삼성전자 or 005930)")
    add_parser.add_argument("target_price", type=int, help="Target price for breakout (원)")
    add_parser.add_argument("--max-units", type=int, default=1, help="Max units to buy (default: 1)")
    add_parser.add_argument("--stop-loss", type=float, help="Custom stop loss %%")
    add_parser.add_argument("--date", "-d", type=str, help="Added date (e.g., 2/6, 2월6일, 02-06). Default: today")

    # remove command
    remove_parser = subparsers.add_parser("remove", help="Remove item from watchlist")
    remove_parser.add_argument("name", type=str, help="Stock name or ticker")

    # update command
    update_parser = subparsers.add_parser("update", help="Update item in watchlist")
    update_parser.add_argument("name", type=str, help="Stock name or ticker")
    update_parser.add_argument("target_price", type=int, nargs="?", help="New target price (원)")
    update_parser.add_argument("--max-units", type=int, help="New max units")
    update_parser.add_argument("--stop-loss", type=float, help="New stop loss %%")
    update_parser.add_argument("--date", "-d", type=str, help="New added date (e.g., 2/6, 2월6일, 02-06)")

    # list command
    subparsers.add_parser("list", help="List all items in watchlist")

    # get command
    get_parser = subparsers.add_parser("get", help="Check if item exists in watchlist")
    get_parser.add_argument("name", type=str, help="Stock name or ticker")

    args = parser.parse_args()

    if args.command == "add":
        added_date = None
        if args.date:
            try:
                added_date = parse_flexible_date(args.date)
            except ValueError as e:
                print(f"[ERROR] {e}")
                return
        add_item(args.name, args.target_price, args.max_units, args.stop_loss, added_date)
    elif args.command == "remove":
        remove_item(args.name)
    elif args.command == "update":
        added_date = None
        if args.date:
            try:
                added_date = parse_flexible_date(args.date)
            except ValueError as e:
                print(f"[ERROR] {e}")
                return
        else:
            # Auto-update added_date to today when other fields change
            if args.target_price is not None or args.max_units is not None or args.stop_loss is not None:
                added_date = date.today()
        update_item(args.name, args.target_price, args.max_units, args.stop_loss, added_date)
    elif args.command == "list":
        list_items()
    elif args.command == "get":
        get_item(args.name)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
