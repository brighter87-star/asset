"""
Portfolio Viewer CLI
View portfolio snapshots and position details.
"""

import argparse
import sys
from datetime import date, datetime
from typing import Optional

from db.connection import get_connection
from services.portfolio_service import get_portfolio_composition
from utils.krx_calendar import is_korea_trading_day_by_samsung


def format_number(value, decimals=0):
    """Format number with thousand separators."""
    if value is None:
        return "N/A"
    if decimals == 0:
        return f"{int(value):,}"
    return f"{float(value):,.{decimals}f}"


def format_currency(value):
    """Format currency in KRW."""
    if value is None:
        return "N/A"
    return f"{format_number(value)}"


def format_percentage(value, decimals=2):
    """Format percentage."""
    if value is None:
        return "N/A"
    sign = "+" if value > 0 else ""
    return f"{sign}{float(value):.{decimals}f}%"


def check_trading_day(check_date: date) -> bool:
    """
    Check if the given date is a trading day.

    Args:
        check_date: Date to check

    Returns:
        True if trading day, False otherwise
    """
    # First, check if data exists in portfolio_snapshot
    # This allows viewing manually generated snapshots
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM portfolio_snapshot WHERE snapshot_date = %s",
                (check_date,)
            )
            count = cur.fetchone()[0]
            if count > 0:
                return True  # Data exists, so we can view it
    finally:
        conn.close()

    # If no data exists and checking today, verify with API
    if check_date == date.today():
        try:
            return is_korea_trading_day_by_samsung()
        except Exception as e:
            print(f"Warning: Could not verify trading day status: {e}")
            return False  # No data and can't verify, so not viewable

    # Past date with no data
    return False


def view_portfolio(snapshot_date: Optional[date] = None):
    """
    View portfolio composition for a specific date.

    Args:
        snapshot_date: Date to view. If None, uses today.
    """
    if snapshot_date is None:
        snapshot_date = date.today()

    # Check if it's a trading day
    if not check_trading_day(snapshot_date):
        print(f"[ERROR] {snapshot_date} is NOT a trading day")
        print("  No portfolio data available for this date.")
        sys.exit(1)

    conn = get_connection()

    try:
        positions = get_portfolio_composition(conn, snapshot_date)

        if not positions:
            print(f"No portfolio data found for {snapshot_date}")
            return

        # Header
        print("=" * 100)
        print(f"Portfolio Snapshot - {snapshot_date}")
        print("=" * 100)

        # Get total portfolio value
        total_value = positions[0].get('total_portfolio_value', 0) if positions else 0

        # Table header
        print(f"\n{'Stock':<20} {'Qty':>8} {'Avg Cost':>12} {'Current':>12} {'Value':>15} {'P&L':>15} {'Return':>10} {'Weight':>8}")
        print("-" * 100)

        total_cost = 0
        total_market_value = 0
        total_pnl = 0

        for pos in positions:
            stock_name = pos['stock_name'] or 'Unknown'
            stock_code = pos['stock_code']
            crd_class = pos['crd_class']

            # Truncate long stock names
            display_name = f"{stock_name[:15]}..." if len(stock_name) > 15 else stock_name
            if crd_class == 'CREDIT':
                display_name = f"{display_name}*"  # Mark credit positions

            qty = pos['total_quantity']
            avg_cost = pos['avg_cost_basis']
            current = pos['current_price']
            market_value = pos['market_value']
            pnl = pos['unrealized_pnl']
            return_pct = pos['unrealized_return_pct']
            weight = pos['portfolio_weight_pct']

            total_cost += pos['total_cost'] or 0
            total_market_value += market_value or 0
            total_pnl += pnl or 0

            # Color code for P&L
            pnl_str = format_currency(pnl)
            return_str = format_percentage(return_pct)

            print(f"{display_name:<20} {format_number(qty):>8} "
                  f"{format_currency(avg_cost):>12} {format_currency(current):>12} "
                  f"{format_currency(market_value):>15} {pnl_str:>15} "
                  f"{return_str:>10} {format_percentage(weight, 1):>8}")

        # Summary
        print("-" * 100)
        total_return_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
        print(f"{'TOTAL':<20} {'':<8} {'':<12} {'':<12} "
              f"{format_currency(total_market_value):>15} {format_currency(total_pnl):>15} "
              f"{format_percentage(total_return_pct):>10} {'100.0%':>8}")

        # Calculate stock exposure
        stock_exposure_pct = (total_market_value / total_value * 100) if total_value > 0 else 0

        print("\n" + "=" * 100)
        print(f"Total Stock Value:     {format_currency(total_market_value)}")
        print(f"Total Portfolio Value: {format_currency(total_value)} (추정자산)")
        print(f"Stock Exposure:        {format_percentage(stock_exposure_pct, 1)}")
        print(f"Total Invested:        {format_currency(total_cost)}")
        print(f"Total P&L:             {format_currency(total_pnl)} ({format_percentage(total_return_pct)})")
        print("=" * 100)
        print("\n* Credit position")

    finally:
        conn.close()


def view_position_detail(stock_code: str):
    """
    View detailed lot breakdown for a specific stock.

    Args:
        stock_code: Stock code to view
    """
    conn = get_connection()

    try:
        # Get all open lots for this stock
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    lot_id,
                    stock_name,
                    crd_class,
                    trade_date,
                    net_quantity,
                    avg_purchase_price,
                    total_cost,
                    current_price,
                    unrealized_pnl,
                    unrealized_return_pct,
                    holding_days
                FROM daily_lots
                WHERE stock_code = %s AND is_closed = FALSE
                ORDER BY trade_date
                """,
                (stock_code,)
            )

            lots = cur.fetchall()

        if not lots:
            print(f"No open positions found for {stock_code}")
            return

        # Extract common info
        stock_name = lots[0][1]

        # Header
        print("=" * 100)
        print(f"{stock_name} ({stock_code}) - {len(lots)} lot(s)")
        print("=" * 100)

        total_qty = 0
        total_cost = 0
        total_pnl = 0

        for i, lot in enumerate(lots, 1):
            (lot_id, stock_name, crd_class, trade_date, net_quantity,
             avg_price, cost, current_price, pnl, return_pct, holding_days) = lot

            total_qty += net_quantity or 0
            total_cost += cost or 0
            total_pnl += pnl or 0

            credit_mark = " [CREDIT]" if crd_class == 'CREDIT' else ""

            print(f"\nLot #{i} - {trade_date}{credit_mark}")
            print("-" * 100)
            print(f"  Quantity:      {format_number(net_quantity):>10} shares")
            print(f"  Purchase Price: {format_currency(avg_price):>15}")
            print(f"  Current Price:  {format_currency(current_price):>15}")
            print(f"  Total Cost:     {format_currency(cost):>15}")
            print(f"  Market Value:   {format_currency(current_price * net_quantity if current_price else 0):>15}")
            print(f"  P&L:            {format_currency(pnl):>15} ({format_percentage(return_pct)})")
            print(f"  Holding Days:   {format_number(holding_days):>10} days")

        # Summary
        print("\n" + "=" * 100)
        print("SUMMARY")
        print("=" * 100)
        print(f"Total Lots:     {len(lots)}")
        print(f"Total Quantity: {format_number(total_qty)} shares")
        print(f"Total Cost:     {format_currency(total_cost)}")

        avg_price_overall = total_cost / total_qty if total_qty > 0 else 0
        print(f"Average Price:  {format_currency(avg_price_overall)}")

        current_price = lots[0][7] if lots else 0
        market_value = current_price * total_qty if current_price else 0
        print(f"Current Price:  {format_currency(current_price)}")
        print(f"Market Value:   {format_currency(market_value)}")

        total_return_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
        print(f"Total P&L:      {format_currency(total_pnl)} ({format_percentage(total_return_pct)})")
        print("=" * 100)

    finally:
        conn.close()


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="View portfolio snapshots and position details",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python view_portfolio.py                    # View today's portfolio
  python view_portfolio.py --date 2025-01-15  # View specific date
  python view_portfolio.py --stock A005930     # View Samsung Electronics lots
        """
    )

    parser.add_argument(
        '--date',
        type=str,
        help='Snapshot date (YYYY-MM-DD). Default: today'
    )

    parser.add_argument(
        '--stock',
        type=str,
        help='Stock code for detailed lot view (e.g., A005930)'
    )

    args = parser.parse_args()

    # Parse date if provided
    snapshot_date = None
    if args.date:
        try:
            snapshot_date = datetime.strptime(args.date, '%Y-%m-%d').date()
        except ValueError:
            print(f"✗ Error: Invalid date format '{args.date}'. Use YYYY-MM-DD")
            sys.exit(1)

    # Execute appropriate view
    if args.stock:
        view_position_detail(args.stock)
    else:
        view_portfolio(snapshot_date)


if __name__ == "__main__":
    main()
