"""
Sync current holdings and account summary from Kiwoom API.
Shows detailed account information including balance, P&L, and holdings.
"""

from db.connection import get_connection
from services.kiwoom_service import sync_holdings_from_kiwoom, sync_account_summary_from_kiwoom


def main():
    print("=" * 80)
    print("Syncing Current Data from Kiwoom API")
    print("=" * 80)

    conn = get_connection()

    try:
        # Step 1: Sync account summary
        print("\n[1/2] Syncing account summary from Kiwoom API...")
        sync_account_summary_from_kiwoom(conn)
        print("OK Synced account summary")

        # Step 2: Sync holdings (includes current prices)
        print("\n[2/2] Syncing current holdings from Kiwoom API...")
        holdings_count = sync_holdings_from_kiwoom(conn)
        print(f"OK Synced {holdings_count} holdings")

        # Display detailed summary
        print("\n" + "=" * 80)
        print("Current Account Status")
        print("=" * 80)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    snapshot_date,
                    acnt_nm,
                    entr,
                    tot_est_amt,
                    aset_evlt_amt,
                    tot_pur_amt,
                    tot_grnt_sella,
                    invt_bsamt,
                    lspft_amt,
                    lspft_rt
                FROM account_summary
                ORDER BY snapshot_date DESC
                LIMIT 1
            """)

            row = cur.fetchone()
            if row:
                snapshot_date = row[0]
                acnt_nm = row[1] or ""
                entr = row[2] or 0
                tot_est_amt = row[3] or 0
                aset_evlt_amt = row[4] or 0
                tot_pur_amt = row[5] or 0
                tot_grnt_sella = row[6] or 0
                invt_bsamt = row[7] or 0
                lspft_amt = row[8] or 0
                lspft_rt = row[9] or 0

                print(f"\n[Account Info]")
                print(f"Date: {snapshot_date}")
                if acnt_nm:
                    print(f"Account: {acnt_nm}")

                print(f"\n[Balance]")
                print(f"Deposit: {entr:>15,} won")
                print(f"Total Est.: {tot_est_amt:>15,} won")

                print(f"\n[Holdings]")
                print(f"Stock Value: {aset_evlt_amt:>15,} won")
                print(f"Purchase Amt: {tot_pur_amt:>15,} won")
                if tot_grnt_sella > 0:
                    print(f"Margin Loan: {tot_grnt_sella:>15,} won")
                    print(f"Net Value: {aset_evlt_amt - tot_grnt_sella:>15,} won")

                print(f"\n[Performance]")
                if invt_bsamt > 0:
                    print(f"Invested: {invt_bsamt:>15,} won")
                if lspft_amt != 0:
                    print(f"Realized P/L: {lspft_amt:>15,} won")
                if lspft_rt != 0:
                    print(f"Return: {lspft_rt:>15.2f} %")

        # Display holdings with current prices
        print("\n" + "=" * 80)
        print("Current Holdings (Top 15)")
        print("=" * 80)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    stk_cd,
                    stk_nm,
                    crd_class,
                    rmnd_qty,
                    avg_prc,
                    cur_prc,
                    evlt_amt,
                    pl_amt,
                    pl_rt
                FROM holdings
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM holdings)
                  AND rmnd_qty > 0
                ORDER BY evlt_amt DESC
                LIMIT 15
            """)

            rows = cur.fetchall()
            if rows:
                print(f"\n{'Code':<10} {'Name':<15} {'Class':<6} {'Qty':<6} {'Avg':<10} {'Cur':<10} {'Value':<12} {'P/L':<12} {'%':>7}")
                print("-" * 100)

                total_value = 0
                total_pl = 0

                for row in rows:
                    stk_cd = row[0]
                    stk_nm = row[1][:15] if row[1] else ""
                    crd_class = row[2]
                    qty = row[3] or 0
                    avg_prc = row[4] or 0
                    cur_prc = row[5] or 0
                    value = row[6] or 0
                    pl_amt = row[7] or 0
                    pl_rt = row[8] or 0

                    total_value += value
                    total_pl += pl_amt

                    print(f"{stk_cd:<10} {stk_nm:<15} {crd_class:<6} {qty:>6} {avg_prc:>10,} {cur_prc:>10,} {value:>12,} {pl_amt:>12,} {pl_rt:>7.2f}")

                print("=" * 100)
                print(f"{'TOTAL':<43} {total_value:>12,} {total_pl:>12,} {(total_pl/total_value*100 if total_value > 0 else 0):>7.2f}")

        conn.close()

        print("\n" + "=" * 80)
        print("OK Sync completed successfully")
        print("=" * 80)

    except Exception as e:
        conn.close()
        print(f"\nERROR Sync failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
