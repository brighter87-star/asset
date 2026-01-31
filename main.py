"""
Asset Management Main Pipeline
Daily batch processing for lot tracking and portfolio analytics.
"""

from datetime import date, timedelta

from db.connection import get_connection
from services.data_sync_service import sync_all
from services.lot_service import construct_daily_lots, update_lot_metrics
from services.portfolio_service import create_portfolio_snapshot


def main():
    """
    Main execution function for daily batch processing.

    Steps:
    1. Sync data from trading database
    2. Construct/update daily lots
    3. Update lot metrics (prices, returns, holding days)
    4. Create portfolio snapshot
    """
    print("=" * 60)
    print("Asset Management Pipeline - Daily Batch")
    print("=" * 60)

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Step 1: Sync data from trading database
    print(f"\n[1/4] Syncing data from trading database...")
    try:
        # For incremental sync: sync_all(start_date=yesterday.strftime('%Y-%m-%d'), snapshot_date=today)
        # For full sync: sync_all(start_date=None, snapshot_date=today)
        sync_all(start_date=None, snapshot_date=today)
        print("OK: Data sync completed")
    except Exception as e:
        print(f"Warning: Data sync failed: {e}")
        print("Continuing with existing data...")
        # Don't return - continue with existing data in case of sync issues

    # Step 2: Construct daily lots
    print(f"\n[2/4] Constructing daily lots...")
    conn = get_connection()
    try:
        # For initial run, process all history
        # For incremental runs, use: start_date=yesterday, end_date=today
        construct_daily_lots(conn, start_date=None, end_date=None)
        print("✓ Daily lots constructed")
    except Exception as e:
        conn.close()
        print(f"✗ Lot construction failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Step 3: Update lot metrics
    print(f"\n[3/4] Updating lot metrics...")
    try:
        updated_count = update_lot_metrics(conn, today)
        print(f"✓ Updated {updated_count} lot(s)")
    except Exception as e:
        conn.close()
        print(f"✗ Metrics update failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # Step 4: Create portfolio snapshot
    print(f"\n[4/4] Creating portfolio snapshot...")
    try:
        snapshot_count = create_portfolio_snapshot(conn, today)
        print(f"✓ Created snapshot with {snapshot_count} position(s)")
    except Exception as e:
        conn.close()
        print(f"✗ Snapshot creation failed: {e}")
        import traceback
        traceback.print_exc()
        return

    conn.close()

    print("\n" + "=" * 60)
    print("✓ Pipeline completed successfully")
    print("=" * 60)


if __name__ == "__main__":
    main()
