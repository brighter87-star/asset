"""
Check account_trade_history data by date.
"""

from db.connection import get_connection


def main():
    conn = get_connection()

    print("=" * 60)
    print("Checking account_trade_history")
    print("=" * 60)

    # Check total count
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) as total FROM account_trade_history")
        result = cur.fetchone()
        total = result[0]
        print(f"\nTotal trade records: {total}")

    # Check date range
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                MIN(trade_date) as min_date,
                MAX(trade_date) as max_date
            FROM account_trade_history
        """)
        result = cur.fetchone()
        if result[0]:
            print(f"Date range: {result[0]} ~ {result[1]}")
        else:
            print("No trade records found!")
            conn.close()
            return

    # Check records by date
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                trade_date,
                COUNT(*) as count,
                SUM(CASE WHEN io_tp_nm LIKE '%매수%' THEN 1 ELSE 0 END) as buy_count,
                SUM(CASE WHEN io_tp_nm LIKE '%매도%' THEN 1 ELSE 0 END) as sell_count
            FROM account_trade_history
            GROUP BY trade_date
            ORDER BY trade_date
        """)

        print("\n" + "=" * 60)
        print("Trade records by date:")
        print("=" * 60)
        print(f"{'Date':<12} {'Total':<8} {'Buy':<8} {'Sell':<8}")
        print("-" * 60)

        for row in cur.fetchall():
            print(f"{str(row[0]):<12} {row[1]:<8} {row[2]:<8} {row[3]:<8}")

    # Check daily_lots
    print("\n" + "=" * 60)
    print("Checking daily_lots")
    print("=" * 60)

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) as total FROM daily_lots WHERE is_closed = FALSE")
        result = cur.fetchone()
        print(f"\nOpen lots: {result[0]}")

    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                trade_date,
                COUNT(*) as lot_count,
                SUM(net_quantity) as total_qty
            FROM daily_lots
            WHERE is_closed = FALSE
            GROUP BY trade_date
            ORDER BY trade_date
        """)

        print("\nLots by trade_date:")
        print("-" * 60)
        print(f"{'Date':<12} {'Lots':<8} {'Total Qty':<12}")
        print("-" * 60)

        for row in cur.fetchall():
            print(f"{str(row[0]):<12} {row[1]:<8} {row[2]:<12}")

    conn.close()


if __name__ == "__main__":
    main()
