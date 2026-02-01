"""
Rebuild daily_lots and holdings from account_trade_history.
Run this after syncing trade history from Kiwoom API.
"""

from datetime import date

from db.connection import get_connection
from services.lot_service import construct_daily_lots, construct_holdings_from_trades, update_lot_metrics
from services.portfolio_service import create_portfolio_snapshot


def main():
    print("=" * 60)
    print("Rebuilding daily_lots and holdings from account_trade_history")
    print("=" * 60)

    conn = get_connection()

    try:
        # Step 1: Clear existing daily_lots
        print("\n[1/5] Clearing existing daily_lots...")
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE daily_lots")
        conn.commit()
        print("✓ Cleared daily_lots table")

        # Step 2: Reconstruct daily_lots from account_trade_history
        print("\n[2/5] Reconstructing daily_lots from account_trade_history...")
        construct_daily_lots(conn, start_date=None, end_date=None)
        print("✓ Daily lots reconstructed (from 2025-12-11)")

        # Step 3: Reconstruct holdings from account_trade_history
        today = date.today()
        print(f"\n[3/5] Reconstructing holdings from account_trade_history...")
        construct_holdings_from_trades(conn, snapshot_date=today)
        print("✓ Holdings reconstructed")

        # Step 4: Update lot metrics
        print(f"\n[4/5] Updating lot metrics...")
        updated_count = update_lot_metrics(conn, today)
        print(f"✓ Updated {updated_count} lot(s)")

        # Step 5: Create portfolio snapshot
        print(f"\n[5/5] Creating portfolio snapshot...")
        snapshot_count = create_portfolio_snapshot(conn, today)
        print(f"✓ Created snapshot with {snapshot_count} position(s)")

        conn.close()

        print("\n" + "=" * 60)
        print("✓ Rebuild completed successfully")
        print("=" * 60)

    except Exception as e:
        conn.close()
        print(f"\n✗ Rebuild failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
