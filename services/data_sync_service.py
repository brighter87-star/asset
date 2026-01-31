"""
Data synchronization service.
Syncs data from Kiwoom API to asset database.
"""

from datetime import date
from typing import Optional

import pymysql

from db.connection import get_connection
from services.kiwoom_service import (
    sync_trade_history_from_kiwoom,
    sync_holdings_from_kiwoom,
    sync_account_summary_from_kiwoom,
)


def sync_account_trade_history(
    conn_asset: pymysql.connections.Connection,
    start_date: Optional[str] = None,
) -> int:
    """
    Placeholder for account_trade_history sync.
    All data is now managed directly in the asset database.

    Args:
        conn_asset: Connection to asset database
        start_date: Optional start date (YYYY-MM-DD). If None, syncs all.

    Returns:
        Number of rows synced (0 - no remote sync)
    """
    print("Note: Trade history is managed directly in the asset database")
    return 0


def sync_holdings(
    conn_asset: pymysql.connections.Connection,
    snapshot_date: Optional[date] = None,
) -> int:
    """
    Placeholder for holdings sync.
    All data is now managed directly in the asset database.

    Args:
        conn_asset: Connection to asset database
        snapshot_date: Date to sync. If None, uses today.

    Returns:
        Number of rows synced (0 - no remote sync)
    """
    print("Note: Holdings data is managed directly in the asset database")
    return 0


def sync_account_summary(
    conn_asset: pymysql.connections.Connection,
    snapshot_date: Optional[date] = None,
) -> int:
    """
    Placeholder for account summary sync.
    All data is now managed directly in the asset database.

    Args:
        conn_asset: Connection to asset database
        snapshot_date: Date to sync. If None, uses today.

    Returns:
        Number of rows synced (0 - no remote sync)
    """
    print("Note: Account summary is managed directly in the asset database")
    return 0


def sync_all(start_date: Optional[str] = None, snapshot_date: Optional[date] = None):
    """
    Sync all necessary data from Kiwoom API to asset database.

    Args:
        start_date: Start date for trade history sync (YYYY-MM-DD). Not used for Kiwoom API.
        snapshot_date: Date for holdings and account_summary. If None, uses today.
    """
    conn_asset = get_connection()

    try:
        # Sync trade history from Kiwoom API
        trades_count = sync_trade_history_from_kiwoom(conn_asset)

        # Sync holdings from Kiwoom API
        holdings_count = sync_holdings_from_kiwoom(conn_asset)

        # Sync account summary from Kiwoom API
        summary_count = sync_account_summary_from_kiwoom(conn_asset)

        print(f"\n✓ Total synced: {trades_count + holdings_count + summary_count} records from Kiwoom API")

    except Exception as e:
        print(f"✗ Synchronization failed: {e}")
        raise
    finally:
        conn_asset.close()


if __name__ == "__main__":
    # Full sync (all history)
    print("Starting data synchronization...")
    sync_all()
