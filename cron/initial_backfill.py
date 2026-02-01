#!/usr/bin/env python3
"""
Initial backfill script for asset management system.
Run this ONCE when setting up a new server to populate historical data.

This script:
1. Creates all database tables
2. Syncs all trade history from start_date
3. Backfills daily portfolio snapshots for all trading days
4. Backfills market index data
5. Constructs lots and portfolio snapshots

Usage:
    python cron/initial_backfill.py
    python cron/initial_backfill.py --start-date 2025-12-11
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import get_connection
from scripts.init_database import init_database
from services.kiwoom_service import (
    sync_trade_history_from_kiwoom,
    sync_holdings_from_kiwoom,
    sync_account_summary_from_kiwoom,
    backfill_daily_snapshots,
    sync_market_index_from_kiwoom,
)
from services.lot_service import construct_daily_lots, update_lot_metrics
from services.portfolio_service import create_portfolio_snapshot, backfill_portfolio_snapshots


def initial_backfill(start_date: date):
    """
    Run initial backfill for all historical data.

    Args:
        start_date: Start date for backfill
    """
    end_date = date.today()

    print("=" * 80)
    print("INITIAL BACKFILL")
    print(f"Date range: {start_date} ~ {end_date}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # Step 1: Initialize database tables
    print("\n[STEP 1] Initializing database tables...")
    init_database(drop_existing=False)

    conn = get_connection()

    try:
        # Step 2: Sync all trade history
        print("\n[STEP 2] Syncing trade history...")
        trade_count = sync_trade_history_from_kiwoom(
            conn,
            start_date=start_date.strftime("%Y%m%d")
        )
        print(f"         Total trades: {trade_count}")

        # Step 3: Sync current holdings
        print("\n[STEP 3] Syncing current holdings...")
        holdings_count = sync_holdings_from_kiwoom(conn)
        print(f"         Holdings: {holdings_count}")

        # Step 4: Sync account summary
        print("\n[STEP 4] Syncing account summary...")
        summary_count = sync_account_summary_from_kiwoom(conn)
        print(f"         Summary: {summary_count}")

        # Step 5: Backfill daily portfolio snapshots
        print("\n[STEP 5] Backfilling daily portfolio snapshots...")
        snapshot_count = backfill_daily_snapshots(conn, start_date, end_date)
        print(f"         Snapshots: {snapshot_count}")

        # Step 6: Sync market index
        print("\n[STEP 6] Syncing market index (KOSPI/KOSDAQ)...")
        index_count = sync_market_index_from_kiwoom(conn, start_date, end_date)
        print(f"         Index records: {index_count}")

        # Step 7: Construct daily lots
        print("\n[STEP 7] Constructing daily lots...")
        construct_daily_lots(conn)

        # Step 8: Update lot metrics
        print("\n[STEP 8] Updating lot metrics...")
        update_lot_metrics(conn, end_date)

        # Step 9: Create portfolio snapshot (today only)
        print("\n[STEP 9] Creating portfolio snapshot (today)...")
        create_portfolio_snapshot(conn, end_date)

        # Step 10: Backfill portfolio snapshots from lots (2026-01-02 onwards)
        # Since daily_lots is reconstructed from trade history, portfolio_snapshot
        # should start from 2026-01-02 (first trading day of 2026)
        print("\n[STEP 10] Backfilling portfolio snapshots from lots...")
        portfolio_start = date(2026, 1, 2)  # First trading day of 2026
        backfill_portfolio_snapshots(conn, portfolio_start, end_date)

        # Get actual counts from DB
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM account_trade_history")
            trade_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM holdings WHERE snapshot_date = %s", (end_date,))
            holdings_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM daily_portfolio_snapshot")
            snapshot_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM market_index")
            index_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM daily_lots")
            lot_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM portfolio_snapshot")
            portfolio_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT snapshot_date) FROM portfolio_snapshot")
            portfolio_days = cur.fetchone()[0]

        print("\n" + "=" * 80)
        print("INITIAL BACKFILL COMPLETE!")
        print(f"Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)

        # Summary (actual DB counts)
        print("\nSummary (DB counts):")
        print(f"  - Trade history: {trade_count} records")
        print(f"  - Holdings (today): {holdings_count} records")
        print(f"  - Daily snapshots: {snapshot_count} records")
        print(f"  - Market index: {index_count} records")
        print(f"  - Lots: {lot_count} records")
        print(f"  - Portfolio positions: {portfolio_count} records ({portfolio_days} days)")

    except Exception as e:
        print(f"\n[ERROR] Initial backfill failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Initial backfill for asset management")
    parser.add_argument(
        "--start-date",
        type=str,
        default="2025-12-11",
        help="Start date for backfill (YYYY-MM-DD). Default: 2025-12-11",
    )
    args = parser.parse_args()

    start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    initial_backfill(start_date)


if __name__ == "__main__":
    main()
