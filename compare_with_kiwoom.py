"""
Compare holdings/daily_lots with current Kiwoom account.
"""

from datetime import date
from db.connection import get_connection
from services.kiwoom_service import KiwoomAPIClient


def main():
    print("=" * 60)
    print("Comparing with Kiwoom Account")
    print("=" * 60)

    # Get current holdings from Kiwoom
    print("\n[1/3] Fetching current holdings from Kiwoom API...")
    client = KiwoomAPIClient()
    kiwoom_holdings = client.get_holdings()

    print(f"✓ Found {len(kiwoom_holdings)} positions in Kiwoom")

    # Get holdings from database
    print("\n[2/3] Fetching holdings from database...")
    conn = get_connection()

    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                stk_cd,
                stk_nm,
                rmnd_qty,
                avg_prc,
                cur_prc,
                crd_class,
                loan_dt
            FROM holdings
            WHERE snapshot_date = %s
            ORDER BY stk_cd
        """, (date.today(),))

        db_holdings = cur.fetchall()

    print(f"✓ Found {len(db_holdings)} positions in database")

    # Compare
    print("\n[3/3] Comparing positions...")
    print("\n" + "=" * 80)
    print("Comparison Results")
    print("=" * 80)

    # Create lookup dictionaries
    kiwoom_dict = {h['stk_cd']: h for h in kiwoom_holdings}
    db_dict = {row[0]: row for row in db_holdings}

    all_stocks = set(kiwoom_dict.keys()) | set(db_dict.keys())

    print(f"\n{'Stock':<10} {'Name':<15} {'Kiwoom Qty':<12} {'DB Qty':<12} {'Diff':<12} {'Status'}")
    print("-" * 80)

    for stock_code in sorted(all_stocks):
        kiwoom_qty = kiwoom_dict[stock_code]['rmnd_qty'] if stock_code in kiwoom_dict else 0
        db_qty = db_dict[stock_code][2] if stock_code in db_dict else 0
        diff = db_qty - kiwoom_qty
        stock_name = (kiwoom_dict[stock_code]['stk_nm'] if stock_code in kiwoom_dict
                     else db_dict[stock_code][1] if stock_code in db_dict else "")[:15]

        status = "✓" if diff == 0 else "✗ MISMATCH"

        print(f"{stock_code:<10} {stock_name:<15} {kiwoom_qty:<12} {db_qty:<12} {diff:<12} {status}")

    # Summary
    print("\n" + "=" * 80)
    mismatches = [s for s in all_stocks if
                  (kiwoom_dict.get(s, {}).get('rmnd_qty', 0) !=
                   (db_dict.get(s, [0,0,0])[2] if s in db_dict else 0))]

    if mismatches:
        print(f"⚠ Found {len(mismatches)} mismatch(es)")
        print("\nMismatched stocks:")
        for stock in mismatches:
            print(f"  - {stock}")
    else:
        print("✓ All positions match!")

    # Check daily_lots for open positions
    print("\n" + "=" * 80)
    print("Open Daily Lots Summary")
    print("=" * 80)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                stock_code,
                stock_name,
                crd_class,
                COUNT(*) as lot_count,
                SUM(net_quantity) as total_qty,
                MIN(trade_date) as first_buy,
                MAX(trade_date) as last_buy
            FROM daily_lots
            WHERE is_closed = FALSE
            GROUP BY stock_code, stock_name, crd_class
            ORDER BY stock_code
        """)

        lots = cur.fetchall()

    print(f"\n{'Stock':<10} {'Name':<15} {'Lots':<6} {'Total Qty':<12} {'First Buy':<12} {'Last Buy':<12}")
    print("-" * 80)

    for lot in lots:
        print(f"{lot[0]:<10} {lot[1][:15]:<15} {lot[3]:<6} {lot[4]:<12} {str(lot[5]):<12} {str(lot[6]):<12}")

    conn.close()


if __name__ == "__main__":
    main()
