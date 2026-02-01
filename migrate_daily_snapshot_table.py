"""
Migrate daily_portfolio_snapshot table to new schema using ka01690 fields.
This will DROP and recreate the table with updated columns.
"""

from db.connection import get_connection


def main():
    print("=" * 80)
    print("Migrating daily_portfolio_snapshot table to new schema")
    print("=" * 80)
    print("\nWARNING: This will DROP the existing table and all data!")
    print("Press Ctrl+C to cancel, or Enter to continue...")
    input()

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            # Drop existing table
            print("\nDropping existing table...")
            cur.execute("DROP TABLE IF EXISTS daily_portfolio_snapshot")
            print("✓ Dropped old table")

            # Create new table with ka01690 schema
            print("\nCreating new table with updated schema...")
            create_sql = """
                CREATE TABLE daily_portfolio_snapshot (
                    snapshot_date DATE PRIMARY KEY,
                    day_stk_asst BIGINT COMMENT '추정자산 (Estimated Asset)',
                    tot_pur_amt BIGINT COMMENT '총매입금액',
                    tot_evlt_amt BIGINT COMMENT '총평가금액',
                    ina_amt BIGINT COMMENT '입금액',
                    outa BIGINT COMMENT '출금액',
                    buy_amt BIGINT COMMENT '매수금액',
                    sell_amt BIGINT COMMENT '매도금액',
                    cmsn BIGINT COMMENT '수수료',
                    tax BIGINT COMMENT '세금',
                    unrealized_pl BIGINT COMMENT '미실현손익',
                    lspft_amt BIGINT COMMENT '실현손익',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_snapshot_date (snapshot_date)
                )
            """

            cur.execute(create_sql)
            conn.commit()

            print("✓ Created new table with updated schema")

            # Verify
            cur.execute("SHOW TABLES LIKE 'daily_portfolio_snapshot'")
            if cur.fetchone():
                print("✓ Table verified")

                # Show columns
                cur.execute("DESCRIBE daily_portfolio_snapshot")
                columns = cur.fetchall()
                print("\nTable columns:")
                for col in columns:
                    print(f"  - {col[0]}: {col[1]}")
            else:
                print("ERROR Table not found")

        conn.close()

        print("\n" + "=" * 80)
        print("OK Migration completed successfully")
        print("=" * 80)
        print("\nNext steps:")
        print("1. Run: python backfill_snapshots.py")
        print("   This will backfill historical data using ka01690 API")

    except Exception as e:
        conn.close()
        print(f"\nERROR Migration failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
