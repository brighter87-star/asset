"""
Add missing columns to account_summary and holdings tables.
Run this on the server after initial setup.
"""

from db.connection import get_connection


def add_account_summary_columns():
    """Add missing columns to account_summary table."""
    conn = get_connection()
    
    columns_to_add = [
        ('acnt_nm', 'VARCHAR(100)'),
        ('brch_nm', 'VARCHAR(100)'),
        ('entr', 'BIGINT'),
        ('d2_entra', 'BIGINT'),
        ('tot_pur_amt', 'BIGINT'),
        ('prsm_dpst_aset_amt', 'BIGINT'),
        ('tot_grnt_sella', 'BIGINT'),
        ('tdy_lspft_amt', 'BIGINT'),
        ('lspft_amt', 'BIGINT'),
        ('tdy_lspft', 'BIGINT'),
        ('lspft2', 'BIGINT'),
        ('lspft', 'BIGINT'),
        ('tdy_lspft_rt', 'DECIMAL(10, 4)'),
        ('lspft_ratio', 'DECIMAL(10, 4)'),
        ('lspft_rt', 'DECIMAL(10, 4)'),
        ('return_code', 'INT'),
        ('return_msg', 'VARCHAR(500)'),
        ('raw_json', 'TEXT'),
    ]
    
    with conn.cursor() as cur:
        # Get existing columns
        cur.execute('DESCRIBE account_summary')
        existing_cols = {row[0] for row in cur.fetchall()}
        
        print('Adding columns to account_summary...')
        for col_name, col_type in columns_to_add:
            if col_name not in existing_cols:
                try:
                    sql = f'ALTER TABLE account_summary ADD COLUMN {col_name} {col_type}'
                    cur.execute(sql)
                    print(f'  + {col_name}')
                except Exception as e:
                    print(f'  ERROR {col_name}: {e}')
    
    conn.commit()
    conn.close()


def add_holdings_columns():
    """Add missing columns to holdings table."""
    conn = get_connection()
    
    columns_to_add = [
        ('account_id', 'BIGINT'),
        ('evlt_amt', 'BIGINT'),
        ('pl_amt', 'BIGINT'),
        ('pl_rt', 'DECIMAL(10, 4)'),
        ('pur_amt', 'BIGINT'),
        ('setl_remn', 'BIGINT'),
        ('pred_buyq', 'INT'),
        ('pred_sellq', 'INT'),
        ('tdy_buyq', 'INT'),
        ('tdy_sellq', 'INT'),
        ('raw_json', 'TEXT'),
    ]
    
    with conn.cursor() as cur:
        # Get existing columns
        cur.execute('DESCRIBE holdings')
        existing_cols = {row[0] for row in cur.fetchall()}
        
        print('\nAdding columns to holdings...')
        for col_name, col_type in columns_to_add:
            if col_name not in existing_cols:
                try:
                    sql = f'ALTER TABLE holdings ADD COLUMN {col_name} {col_type}'
                    cur.execute(sql)
                    print(f'  + {col_name}')
                except Exception as e:
                    print(f'  ERROR {col_name}: {e}')
    
    conn.commit()
    conn.close()


if __name__ == '__main__':
    print('=' * 60)
    print('Adding missing columns to database')
    print('=' * 60)
    
    add_account_summary_columns()
    add_holdings_columns()
    
    print('\n' + '=' * 60)
    print('Done!')
    print('=' * 60)
