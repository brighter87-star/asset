"""
Create daily_portfolio_snapshot table.
"""

from db.connection import get_connection


def main():
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            # Drop existing table if needed
            # cur.execute("DROP TABLE IF EXISTS daily_portfolio_snapshot")

            # Create table
            create_sql = """
                CREATE TABLE IF NOT EXISTS daily_portfolio_snapshot (
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

            print("OK Created daily_portfolio_snapshot table")

            # Verify
            cur.execute("SHOW TABLES LIKE 'daily_portfolio_snapshot'")
            if cur.fetchone():
                print("OK Table verified")
            else:
                print("ERROR Table not found")

        conn.close()

    except Exception as e:
        conn.close()
        print(f"ERROR Failed to create table: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
