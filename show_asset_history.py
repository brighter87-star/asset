"""
Show daily asset history with performance tracking.
Tracks Presumed Asset (total value after liquidation) and portfolio changes over time.
Includes deposit/withdrawal tracking for calculating money-weighted returns.
"""

from db.connection import get_connection
from datetime import datetime


def main():
    print("=" * 140)
    print("Daily Asset History (with Cash Flows)")
    print("=" * 140)

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            # Get all daily snapshots
            cur.execute("""
                SELECT
                    snapshot_date,
                    day_stk_asst,
                    tot_evlt_amt,
                    tot_pur_amt,
                    ina_amt,
                    outa,
                    unrealized_pl,
                    lspft_amt
                FROM daily_portfolio_snapshot
                ORDER BY snapshot_date ASC
            """)

            rows = cur.fetchall()

            if rows:
                print(f"\n{'Date':<12} {'Est. Asset':<15} {'Stock Value':<13} {'Purchase':<13} {'Deposit':<11} {'Withdraw':<11} {'Daily Chg':<13} {'Daily %':<9} {'Total P/L':<13}")
                print("-" * 140)

                prev_est_asset = None
                cumulative_deposit = 0
                cumulative_withdrawal = 0

                for row in rows:
                    snapshot_date = row[0]
                    day_stk_asst = row[1] or 0
                    tot_evlt_amt = row[2] or 0
                    tot_pur_amt = row[3] or 0
                    ina_amt = row[4] or 0
                    outa = row[5] or 0
                    unrealized_pl = row[6] or 0
                    lspft_amt = row[7] or 0

                    cumulative_deposit += ina_amt
                    cumulative_withdrawal += outa

                    # Calculate daily change (excluding deposit/withdrawal)
                    if prev_est_asset is not None:
                        daily_change_raw = day_stk_asst - prev_est_asset
                        daily_change = daily_change_raw - ina_amt + outa  # Adjust for cash flows
                        daily_pct = (daily_change / prev_est_asset * 100) if prev_est_asset > 0 else 0
                    else:
                        daily_change = 0
                        daily_pct = 0

                    prev_est_asset = day_stk_asst

                    # Total P/L = Unrealized + Realized
                    total_pl = unrealized_pl + lspft_amt

                    print(f"{snapshot_date!s:<12} {day_stk_asst:>14,} {tot_evlt_amt:>12,} {tot_pur_amt:>12,} {ina_amt:>10,} {outa:>10,} {daily_change:>12,} {daily_pct:>8.2f} {total_pl:>12,}")

                # Summary statistics
                if len(rows) > 1:
                    first_est_asset = rows[0][1] or 0
                    last_est_asset = rows[-1][1] or 0

                    net_cash_flow = cumulative_deposit - cumulative_withdrawal

                    print("\n" + "=" * 140)
                    print(f"Period: {rows[0][0]} to {rows[-1][0]} ({len(rows)} days)")
                    print(f"\nAsset Summary:")
                    print(f"Starting Estimated Asset: {first_est_asset:>15,} won")
                    print(f"Ending Estimated Asset:   {last_est_asset:>15,} won")

                    print(f"\nCash Flow Summary:")
                    print(f"Total Deposits:           {cumulative_deposit:>15,} won")
                    print(f"Total Withdrawals:        {cumulative_withdrawal:>15,} won")
                    print(f"Net Cash Flow:            {net_cash_flow:>15,} won")

                    # Calculate returns
                    if first_est_asset > 0:
                        # Simple return (not considering cash flows)
                        simple_return = last_est_asset - first_est_asset
                        simple_return_pct = (simple_return / first_est_asset * 100)

                        # Money-weighted return (considering cash flows)
                        # Simple approximation: (Ending - Starting - Net Cash Flow) / Starting
                        investment_return = last_est_asset - first_est_asset - net_cash_flow
                        if first_est_asset + net_cash_flow > 0:
                            mwr_pct = (investment_return / (first_est_asset + net_cash_flow / 2) * 100)
                        else:
                            mwr_pct = 0

                        print(f"\nReturn Analysis:")
                        print(f"Simple Return:            {simple_return:>15,} won ({simple_return_pct:>+.2f}%)")
                        print(f"Investment Return:        {investment_return:>15,} won")
                        print(f"Money-Weighted Return:    {mwr_pct:>15.2f}%")

            else:
                print("\nNo historical data found")
                print("\nRun 'python sync_current_data.py' to create daily snapshots")

        conn.close()

    except Exception as e:
        conn.close()
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
