#!/usr/bin/env python3
"""
Daily synchronization script for asset management system.
Syncs all data from Kiwoom API to database.

This script is idempotent - safe to run multiple times.
Designed to be run by cron at market close (15:35 KST).

Usage:
    python cron/daily_sync.py              # Sync today's data
    python cron/daily_sync.py --date 2026-01-30  # Sync specific date
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db.connection import get_connection
from services.kiwoom_service import (
    sync_trade_history_from_kiwoom,
    sync_holdings_from_kiwoom,
    sync_account_summary_from_kiwoom,
    sync_daily_snapshot_from_kiwoom,
    sync_market_index_from_kiwoom,
)
from services.lot_service import construct_daily_lots, update_lot_metrics
from services.portfolio_service import create_portfolio_snapshot


def daily_sync(target_date: date = None):
    """
    Run daily synchronization for all data.

    Args:
        target_date: Date to sync. If None, uses today.
    """
    if target_date is None:
        target_date = date.today()

    print("=" * 80)
    print(f"Daily Sync - {target_date}")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    conn = get_connection()

    try:
        # 1. Sync trade history (idempotent - INSERT IGNORE)
        print("\n[1/7] Syncing trade history...")
        trade_count = sync_trade_history_from_kiwoom(conn, start_date=target_date.strftime("%Y%m%d"))
        print(f"      Trade records: {trade_count}")

        # 2. Sync holdings
        print("\n[2/7] Syncing holdings...")
        holdings_count = sync_holdings_from_kiwoom(conn)
        print(f"      Holdings records: {holdings_count}")

        # 3. Sync account summary
        print("\n[3/7] Syncing account summary...")
        summary_count = sync_account_summary_from_kiwoom(conn)
        print(f"      Summary records: {summary_count}")

        # 4. Sync daily portfolio snapshot (for TWR/MWR calculation)
        print("\n[4/7] Syncing daily portfolio snapshot...")
        snapshot_count = sync_daily_snapshot_from_kiwoom(conn, target_date)
        print(f"      Snapshot records: {snapshot_count}")

        # 5. Sync market index (KOSPI/KOSDAQ)
        print("\n[5/7] Syncing market index...")
        index_count = sync_market_index_from_kiwoom(conn)
        print(f"      Index records: {index_count}")

        # 6. Construct/update daily lots
        print("\n[6/7] Constructing daily lots...")
        lot_count = construct_daily_lots(conn)
        print(f"      Lots processed: {lot_count}")

        # 7. Update lot metrics and create portfolio snapshot
        print("\n[7/7] Updating metrics and creating portfolio snapshot...")
        update_lot_metrics(conn, target_date)
        portfolio_count = create_portfolio_snapshot(conn, target_date)
        print(f"      Portfolio positions: {portfolio_count}")

        print("\n" + "=" * 80)
        print(f"Daily Sync Complete!")
        print(f"Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)

    except Exception as e:
        print(f"\n[ERROR] Daily sync failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Daily sync for asset management")
    parser.add_argument(
        "--date",
        type=str,
        help="Target date (YYYY-MM-DD). Default: today",
    )
    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    daily_sync(target_date)


if __name__ == "__main__":
    main()
