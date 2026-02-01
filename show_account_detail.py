"""
Show detailed account summary with all fields from account_summary table.
This helps analyze the actual net worth after liquidating all positions.
"""

from db.connection import get_connection


def main():
    print("=" * 100)
    print("Detailed Account Summary (All Fields)")
    print("=" * 100)

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    snapshot_date,
                    acnt_nm,
                    brch_nm,
                    entr,
                    d2_entra,
                    tot_est_amt,
                    aset_evlt_amt,
                    tot_pur_amt,
                    prsm_dpst_aset_amt,
                    tot_grnt_sella,
                    tdy_lspft_amt,
                    invt_bsamt,
                    lspft_amt,
                    tdy_lspft,
                    lspft2,
                    lspft,
                    tdy_lspft_rt,
                    lspft_ratio,
                    lspft_rt,
                    return_code,
                    return_msg
                FROM account_summary
                ORDER BY snapshot_date DESC
                LIMIT 1
            """)

            row = cur.fetchone()
            if row:
                snapshot_date = row[0]
                acnt_nm = row[1] or ""
                brch_nm = row[2] or ""
                entr = row[3] or 0
                d2_entra = row[4] or 0
                tot_est_amt = row[5] or 0
                aset_evlt_amt = row[6] or 0
                tot_pur_amt = row[7] or 0
                prsm_dpst_aset_amt = row[8] or 0
                tot_grnt_sella = row[9] or 0
                tdy_lspft_amt = row[10] or 0
                invt_bsamt = row[11] or 0
                lspft_amt = row[12] or 0
                tdy_lspft = row[13] or 0
                lspft2 = row[14] or 0
                lspft = row[15] or 0
                tdy_lspft_rt = row[16] or 0.0
                lspft_ratio = row[17] or 0.0
                lspft_rt = row[18] or 0.0
                return_code = row[19] or 0
                return_msg = row[20] or ""

                print(f"\n[Basic Info]")
                print(f"Date: {snapshot_date}")
                print(f"Account: {acnt_nm}")
                print(f"Branch: {brch_nm}")

                print(f"\n[Cash Balance]")
                print(f"D+0 Deposit (entr):          {entr:>15,} won")
                print(f"D+2 Deposit (d2_entra):      {d2_entra:>15,} won  ← Withdrawable")

                print(f"\n[Total Asset]")
                print(f"Total Est. (tot_est_amt):    {tot_est_amt:>15,} won  ← Net Worth")
                print(f"Presumed Asset (prsm_dpst):  {prsm_dpst_aset_amt:>15,} won")

                print(f"\n[Stock Holdings]")
                print(f"Stock Value (aset_evlt_amt): {aset_evlt_amt:>15,} won")
                print(f"Purchase Amt (tot_pur_amt):  {tot_pur_amt:>15,} won")
                print(f"Unrealized P/L:              {aset_evlt_amt - tot_pur_amt:>15,} won")

                if tot_grnt_sella > 0:
                    print(f"\n[Margin/Credit]")
                    print(f"Margin Loan (tot_grnt_sella): {tot_grnt_sella:>15,} won")
                    print(f"Net Stock Value:              {aset_evlt_amt - tot_grnt_sella:>15,} won")

                print(f"\n[Realized P/L]")
                if invt_bsamt > 0:
                    print(f"Invested (invt_bsamt):       {invt_bsamt:>15,} won")
                print(f"Realized P/L (lspft_amt):    {lspft_amt:>15,} won")
                print(f"Realized P/L 2 (lspft2):     {lspft2:>15,} won")
                print(f"Realized P/L 3 (lspft):      {lspft:>15,} won")
                if lspft_rt != 0:
                    print(f"Realized Return (lspft_rt):  {lspft_rt:>15.2f} %")

                print(f"\n[Today's Performance]")
                print(f"Today P/L (tdy_lspft_amt):   {tdy_lspft_amt:>15,} won")
                print(f"Today P/L 2 (tdy_lspft):     {tdy_lspft:>15,} won")
                if tdy_lspft_rt != 0:
                    print(f"Today Return (tdy_lspft_rt): {tdy_lspft_rt:>15.2f} %")

                # Calculate liquidation value
                print("\n" + "=" * 100)
                print("Liquidation Analysis (if all positions are closed)")
                print("=" * 100)

                # Liquidation value = Cash after selling all stocks and repaying margin
                liquidation_cash = d2_entra + aset_evlt_amt - tot_grnt_sella

                print(f"\nD+2 Deposit:                 {d2_entra:>15,} won")
                print(f"+ Stock Value:               {aset_evlt_amt:>15,} won")
                if tot_grnt_sella > 0:
                    print(f"- Margin Loan:               {tot_grnt_sella:>15,} won")
                print(f"= Total Cash After Liq.:     {liquidation_cash:>15,} won")

                print(f"\nTotal Est. (from API):       {tot_est_amt:>15,} won")
                print(f"Difference:                  {liquidation_cash - tot_est_amt:>15,} won")

                if return_msg:
                    print(f"\n[API Response]")
                    print(f"Code: {return_code}")
                    print(f"Message: {return_msg}")

            else:
                print("\nNo account summary data found")

        conn.close()

    except Exception as e:
        conn.close()
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
