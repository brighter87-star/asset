"""
Sync data from remote trading database to local asset database.
Run this after establishing SSH tunnel: ssh -L 3307:localhost:3306 user@server
"""

from datetime import date
from typing import Optional

import pymysql


def get_remote_connection():
    """Get connection to remote trading database (via SSH tunnel)."""
    return pymysql.connect(
        host="localhost",
        port=3307,  # SSH tunnel port
        user="brighter87",
        password="!Wjd06Gns30",
        database="trading",
        charset="utf8mb4",
        autocommit=False,
    )


def get_local_connection():
    """Get connection to local asset database."""
    return pymysql.connect(
        host="localhost",
        user="brighter87",
        password="!Wjd06Gns30",
        database="asset",
        charset="utf8mb4",
        autocommit=False,
    )


def sync_trade_history(conn_local, conn_remote, start_date: Optional[str] = None):
    """Sync account_trade_history from remote to local."""
    print("\n[1/3] Syncing trade history...")

    where_clause = ""
    params = {}

    if start_date:
        where_clause = "WHERE trade_date >= %(start_date)s"
        params["start_date"] = start_date

    with conn_remote.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            f"""
            SELECT
                ord_no, stk_cd, stk_nm, io_tp_nm, crd_class,
                trade_date, ord_tm, cntr_qty, cntr_uv, loan_dt
            FROM account_trade_history
            {where_clause}
            ORDER BY trade_date ASC, ord_tm ASC, id ASC
            """,
            params,
        )

        rows = cur.fetchall()

    print(f"  Found {len(rows)} trade records")

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

    with conn_local.cursor() as cur:
        for row in rows:
            cur.execute(insert_sql, row)

    conn_local.commit()
    print(f"  Synced {len(rows)} trade records")
    return len(rows)


def sync_holdings(conn_local, conn_remote, snapshot_date: Optional[date] = None):
    """Sync holdings from remote to local."""
    print("\n[2/3] Syncing holdings...")

    if snapshot_date is None:
        snapshot_date = date.today()

    with conn_remote.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT
                snapshot_date, stk_cd, stk_nm, rmnd_qty,
                avg_prc, cur_prc, loan_dt,
                (CASE WHEN loan_dt IS NULL OR loan_dt = '' THEN 'CASH' ELSE 'CREDIT' END) as crd_class
            FROM holdings
            WHERE snapshot_date = %s
            """,
            (snapshot_date,),
        )

        rows = cur.fetchall()

    print(f"  Found {len(rows)} holdings records")

    if not rows:
        return 0

    # Delete existing data
    with conn_local.cursor() as cur:
        cur.execute("DELETE FROM holdings WHERE snapshot_date = %s", (snapshot_date,))

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

    with conn_local.cursor() as cur:
        for row in rows:
            cur.execute(insert_sql, row)

    conn_local.commit()
    print(f"  Synced {len(rows)} holdings records")
    return len(rows)


def sync_account_summary(conn_local, conn_remote, snapshot_date: Optional[date] = None):
    """Sync account_summary from remote to local."""
    print("\n[3/3] Syncing account summary...")

    if snapshot_date is None:
        snapshot_date = date.today()

    with conn_remote.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            """
            SELECT
                snapshot_date, aset_evlt_amt, tot_est_amt, invt_bsamt
            FROM account_summary
            WHERE snapshot_date = %s
            """,
            (snapshot_date,),
        )

        row = cur.fetchone()

    if not row:
        print("  No account summary found")
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

    with conn_local.cursor() as cur:
        cur.execute(insert_sql, row)

    conn_local.commit()
    print(f"  Synced account summary")
    return 1


def main():
    """Main sync function."""
    print("=" * 60)
    print("Remote Database Sync")
    print("=" * 60)
    print("\nMake sure SSH tunnel is running:")
    print("  ssh -L 3307:localhost:3306 brighter87@your-server")
    print()

    try:
        print("Connecting to remote database...")
        conn_remote = get_remote_connection()
        print("  OK: Connected to remote trading database")

        print("Connecting to local database...")
        conn_local = get_local_connection()
        print("  OK: Connected to local asset database")

    except Exception as e:
        print(f"\nConnection failed: {e}")
        print("\nTroubleshooting:")
        print("  1. Check if SSH tunnel is running")
        print("  2. Verify database credentials")
        print("  3. Check if remote MySQL is accessible")
        return

    try:
        # Clear local sample data first
        print("\nClearing sample data...")
        with conn_local.cursor() as cur:
            cur.execute("DELETE FROM portfolio_snapshot")
            cur.execute("DELETE FROM daily_lots")
            cur.execute("DELETE FROM account_summary")
            cur.execute("DELETE FROM holdings")
            cur.execute("DELETE FROM account_trade_history")
        conn_local.commit()
        print("  Sample data cleared")

        # Sync all data
        today = date.today()

        # Full trade history sync (can specify start_date for incremental)
        trades_count = sync_trade_history(conn_local, conn_remote, start_date=None)

        # Today's holdings
        holdings_count = sync_holdings(conn_local, conn_remote, today)

        # Today's account summary
        summary_count = sync_account_summary(conn_local, conn_remote, today)

        print("\n" + "=" * 60)
        print("Sync completed successfully!")
        print(f"  Trades: {trades_count}")
        print(f"  Holdings: {holdings_count}")
        print(f"  Summary: {summary_count}")
        print("=" * 60)
        print("\nNext step:")
        print("  Run: python test_pipeline.py")

    except Exception as e:
        print(f"\nSync failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        conn_remote.close()
        conn_local.close()


if __name__ == "__main__":
    main()
