-- Enhanced account_summary and holdings tables matching assetmanager structure
-- Run this to add missing columns to existing tables

USE asset;

-- ============================================================
-- Update account_summary table with additional fields
-- ============================================================

-- Add new columns if they don't exist
ALTER TABLE account_summary
ADD COLUMN IF NOT EXISTS acnt_nm VARCHAR(100) COMMENT '계좌명',
ADD COLUMN IF NOT EXISTS brch_nm VARCHAR(100) COMMENT '지점명',
ADD COLUMN IF NOT EXISTS entr BIGINT COMMENT '입금',
ADD COLUMN IF NOT EXISTS d2_entra BIGINT COMMENT 'D+2입금',
ADD COLUMN IF NOT EXISTS tot_pur_amt BIGINT COMMENT '총매입금액',
ADD COLUMN IF NOT EXISTS prsm_dpst_aset_amt BIGINT COMMENT '추정예탁자산',
ADD COLUMN IF NOT EXISTS tot_grnt_sella BIGINT COMMENT '총융자금',
ADD COLUMN IF NOT EXISTS tdy_lspft_amt BIGINT COMMENT '당일실현손익금액',
ADD COLUMN IF NOT EXISTS lspft_amt BIGINT COMMENT '실현손익금액',
ADD COLUMN IF NOT EXISTS tdy_lspft BIGINT COMMENT '당일실현손익',
ADD COLUMN IF NOT EXISTS lspft2 BIGINT COMMENT '실현손익2',
ADD COLUMN IF NOT EXISTS lspft BIGINT COMMENT '실현손익',
ADD COLUMN IF NOT EXISTS tdy_lspft_rt DECIMAL(10, 4) COMMENT '당일실현손익률',
ADD COLUMN IF NOT EXISTS lspft_ratio DECIMAL(10, 4) COMMENT '실현손익비율',
ADD COLUMN IF NOT EXISTS lspft_rt DECIMAL(10, 4) COMMENT '실현손익률',
ADD COLUMN IF NOT EXISTS return_code INT COMMENT 'API 응답코드',
ADD COLUMN IF NOT EXISTS return_msg VARCHAR(500) COMMENT 'API 응답메시지',
ADD COLUMN IF NOT EXISTS raw_json TEXT COMMENT '원본 JSON';

-- ============================================================
-- Update holdings table with additional fields
-- ============================================================

ALTER TABLE holdings
ADD COLUMN IF NOT EXISTS account_id BIGINT COMMENT '계좌ID',
ADD COLUMN IF NOT EXISTS evlt_amt BIGINT COMMENT '평가금액',
ADD COLUMN IF NOT EXISTS pl_amt BIGINT COMMENT '손익금액',
ADD COLUMN IF NOT EXISTS pl_rt DECIMAL(10, 4) COMMENT '손익률',
ADD COLUMN IF NOT EXISTS pur_amt BIGINT COMMENT '매입금액',
ADD COLUMN IF NOT EXISTS setl_remn BIGINT COMMENT '미결제잔고',
ADD COLUMN IF NOT EXISTS pred_buyq INT COMMENT '주문가능매수수량',
ADD COLUMN IF NOT EXISTS pred_sellq INT COMMENT '주문가능매도수량',
ADD COLUMN IF NOT EXISTS tdy_buyq INT COMMENT '당일매수수량',
ADD COLUMN IF NOT EXISTS tdy_sellq INT COMMENT '당일매도수량',
ADD COLUMN IF NOT EXISTS raw_json TEXT COMMENT '원본 JSON';

-- Add index for better query performance
CREATE INDEX IF NOT EXISTS idx_holdings_account ON holdings(account_id);
CREATE INDEX IF NOT EXISTS idx_holdings_snapshot_stk ON holdings(snapshot_date, stk_cd);
