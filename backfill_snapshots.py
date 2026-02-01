"""
Backfill daily portfolio snapshots from 2025-12-11 to today.
Uses ka01690 API which supports historical queries via dt parameter.
Only syncs trading days (excluding weekends and holidays).
"""

from datetime import date
from db.connection import get_connection
from services.kiwoom_service import backfill_daily_snapshots


def main():
    print("=" * 80)
    print("Backfilling Daily Portfolio Snapshots")
    print("=" * 80)

    # Start date: December 11, 2025
    start_date = date(2025, 12, 11)
    end_date = date.today()

    print(f"\nBackfilling from {start_date} to {end_date}")
    print(f"This will only sync trading days (weekdays)")
    print()

    conn = get_connection()

    try:
        synced_count = backfill_daily_snapshots(conn, start_date, end_date)

        print()
        print("=" * 80)
        print(f"OK Backfill completed: {synced_count} records synced")
        print("=" * 80)

        conn.close()

    except Exception as e:
        conn.close()
        print(f"\nERROR Backfill failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
