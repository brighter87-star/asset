"""
Data synchronization service.
Syncs necessary data from trading database to asset database.
"""

from datetime import date
from typing import Optional

import pymysql

from db.connection import get_connection, get_trading_connection


def sync_account_trade_history(
    conn_asset: pymysql.connections.Connection,
    conn_trading: pymysql.connections.Connection,
    start_date: Optional[str] = None,
) -> int:
    """
    Sync account_trade_history from trading DB to asset DB.

    Args:
        conn_asset: Connection to asset database
        conn_trading: Connection to trading database
        start_date: Optional start date (YYYY-MM-DD). If None, syncs all.

    Returns:
        Number of rows synced
    """
    with conn_trading.cursor(pymysql.cursors.DictCursor) as cur_trading:
        where_clause = ""
        params = {}

        if start_date:
            where_clause = "WHERE trade_date >= %(start_date)s"
            params["start_date"] = start_date

        cur_trading.execute(
            f"""
            SELECT
                ord_no,
                stk_cd,
                stk_nm,
                io_tp_nm,
                crd_class,
                trade_date,
                ord_tm,
                cntr_qty,
                cntr_uv,
                loan_dt
            FROM account_trade_history
            {where_clause}
            ORDER BY trade_date ASC, ord_tm ASC, id ASC
            """,
            params,
        )

        rows = cur_trading.fetchall()

    if not rows:
        return 0

    insert_sql = """
        INSERT INTO account_trade_history (
            ord_no, stk_cd, stk_nm, io_tp_nm, crd_class,
            trade_date, ord_tm, cntr_qty, cntr_uv, loan_dt
        )
        VALUES (
            %(ord_no)s, %(stk_cd)s, %(stk_nm)s, %(io_tp_nm)s, %(crd_class)s,
            %(trade_date)s, %(ord_tm)s, %(cntr_qty)s, %(cntr_uv)s, %(loan_dt)s
        )
        ON DUPLICATE KEY UPDATE
            stk_nm = VALUES(stk_nm),
            cntr_qty = VALUES(cntr_qty),
            cntr_uv = VALUES(cntr_uv)
    """

    with conn_asset.cursor() as cur_asset:
        for row in rows:
            cur_asset.execute(insert_sql, row)

    conn_asset.commit()
    return len(rows)


def sync_holdings(
    conn_asset: pymysql.connections.Connection,
    conn_trading: pymysql.connections.Connection,
    snapshot_date: Optional[date] = None,
) -> int:
    """
    Sync holdings from trading DB to asset DB for a specific date.

    Args:
        conn_asset: Connection to asset database
        conn_trading: Connection to trading database
        snapshot_date: Date to sync. If None, uses today.

    Returns:
        Number of rows synced
    """
    if snapshot_date is None:
        snapshot_date = date.today()

    with conn_trading.cursor(pymysql.cursors.DictCursor) as cur_trading:
        cur_trading.execute(
            """
            SELECT
                snapshot_date,
                stk_cd,
                stk_nm,
                rmnd_qty,
                avg_prc,
                cur_prc,
                loan_dt,
                (CASE WHEN loan_dt IS NULL OR loan_dt = '' THEN 'CASH' ELSE 'CREDIT' END) as crd_class
            FROM holdings
            WHERE snapshot_date = %s
            """,
            (snapshot_date,),
        )

        rows = cur_trading.fetchall()

    if not rows:
        return 0

    # Delete existing data for this snapshot date
    with conn_asset.cursor() as cur_asset:
        cur_asset.execute(
            "DELETE FROM holdings WHERE snapshot_date = %s",
            (snapshot_date,),
        )

    insert_sql = """
        INSERT INTO holdings (
            snapshot_date, stk_cd, stk_nm, rmnd_qty,
            avg_prc, cur_prc, loan_dt, crd_class
        )
        VALUES (
            %(snapshot_date)s, %(stk_cd)s, %(stk_nm)s, %(rmnd_qty)s,
            %(avg_prc)s, %(cur_prc)s, %(loan_dt)s, %(crd_class)s
        )
    """

    with conn_asset.cursor() as cur_asset:
        for row in rows:
            cur_asset.execute(insert_sql, row)

    conn_asset.commit()
    return len(rows)


def sync_account_summary(
    conn_asset: pymysql.connections.Connection,
    conn_trading: pymysql.connections.Connection,
    snapshot_date: Optional[date] = None,
) -> int:
    """
    Sync account_summary from trading DB to asset DB for a specific date.

    Args:
        conn_asset: Connection to asset database
        conn_trading: Connection to trading database
        snapshot_date: Date to sync. If None, uses today.

    Returns:
        Number of rows synced
    """
    if snapshot_date is None:
        snapshot_date = date.today()

    with conn_trading.cursor(pymysql.cursors.DictCursor) as cur_trading:
        cur_trading.execute(
            """
            SELECT
                snapshot_date,
                aset_evlt_amt,
                tot_est_amt,
                invt_bsamt
            FROM account_summary
            WHERE snapshot_date = %s
            """,
            (snapshot_date,),
        )

        row = cur_trading.fetchone()

    if not row:
        return 0

    insert_sql = """
        INSERT INTO account_summary (
            snapshot_date, aset_evlt_amt, tot_est_amt, invt_bsamt
        )
        VALUES (
            %(snapshot_date)s, %(aset_evlt_amt)s, %(tot_est_amt)s, %(invt_bsamt)s
        )
        ON DUPLICATE KEY UPDATE
            aset_evlt_amt = VALUES(aset_evlt_amt),
            tot_est_amt = VALUES(tot_est_amt),
            invt_bsamt = VALUES(invt_bsamt)
    """

    with conn_asset.cursor() as cur_asset:
        cur_asset.execute(insert_sql, row)

    conn_asset.commit()
    return 1


def sync_all(start_date: Optional[str] = None, snapshot_date: Optional[date] = None):
    """
    Sync all necessary data from trading DB to asset DB.

    Args:
        start_date: Start date for trade history sync (YYYY-MM-DD). If None, syncs all.
        snapshot_date: Date for holdings and account_summary. If None, uses today.
    """
    conn_asset = get_connection()
    conn_trading = get_trading_connection()

    try:
        # Sync trade history (full or incremental)
        trades_count = sync_account_trade_history(conn_asset, conn_trading, start_date)
        print(f"✓ Synced {trades_count} trade history records")

        # Sync holdings for the snapshot date
        holdings_count = sync_holdings(conn_asset, conn_trading, snapshot_date)
        print(f"✓ Synced {holdings_count} holdings records")

        # Sync account summary for the snapshot date
        summary_count = sync_account_summary(conn_asset, conn_trading, snapshot_date)
        print(f"✓ Synced {summary_count} account summary record")

        print(f"\nTotal synced: {trades_count + holdings_count + summary_count} records")

    finally:
        conn_asset.close()
        conn_trading.close()


if __name__ == "__main__":
    # Full sync (all history)
    print("Starting data synchronization...")
    sync_all()
