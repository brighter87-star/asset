-- Asset Management Database - Full Schema Initialization
-- Database: asset
-- Run this script to create all tables from scratch
-- Usage: mysql -u root -p < db/init_all_tables.sql

-- Create database if not exists
CREATE DATABASE IF NOT EXISTS asset DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE asset;

-- ============================================================
-- Drop all existing tables (in correct order due to dependencies)
-- ============================================================
DROP TABLE IF EXISTS portfolio_snapshot;
DROP TABLE IF EXISTS daily_lots;
DROP TABLE IF EXISTS holdings;
DROP TABLE IF EXISTS account_trade_history;
DROP TABLE IF EXISTS account_summary;
DROP TABLE IF EXISTS daily_portfolio_snapshot;
DROP TABLE IF EXISTS market_index;

-- ============================================================
-- Table 1: account_trade_history
-- Purpose: Trade history synced from Kiwoom API
-- ============================================================
CREATE TABLE account_trade_history (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    ord_no VARCHAR(50) UNIQUE NOT NULL COMMENT '주문번호',
    stk_cd VARCHAR(20) COMMENT '종목코드',
    stk_nm VARCHAR(100) COMMENT '종목명',
    io_tp_nm VARCHAR(50) COMMENT '매매구분',
    crd_class VARCHAR(10) COMMENT '신용구분',
    trade_date DATE COMMENT '거래일자',
    ord_tm CHAR(8) COMMENT '주문시간',
    cntr_qty INT COMMENT '체결수량',
    cntr_uv INT COMMENT '체결단가',
    loan_dt VARCHAR(20) COMMENT '대출일자',

    INDEX idx_trade_date (trade_date),
    INDEX idx_stock_code (stk_cd),
    INDEX idx_crd_class (crd_class),
    INDEX idx_composite (stk_cd, crd_class, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='계좌 거래내역 테이블';

-- ============================================================
-- Table 2: holdings
-- Purpose: Current holdings synced from Kiwoom API
-- ============================================================
CREATE TABLE holdings (
    snapshot_date DATE COMMENT '스냅샷 일자',
    stk_cd VARCHAR(20) COMMENT '종목코드',
    stk_nm VARCHAR(100) COMMENT '종목명',
    rmnd_qty INT COMMENT '잔고수량',
    avg_prc INT COMMENT '평균단가',
    cur_prc INT COMMENT '현재가',
    loan_dt VARCHAR(20) COMMENT '대출일자',
    crd_class VARCHAR(10) COMMENT '신용구분',

    -- Extended fields
    account_id BIGINT COMMENT '계좌ID',
    evlt_amt BIGINT COMMENT '평가금액',
    pl_amt BIGINT COMMENT '손익금액',
    pl_rt DECIMAL(10, 4) COMMENT '손익률',
    pur_amt BIGINT COMMENT '매입금액',
    setl_remn BIGINT COMMENT '미결제잔고',
    pred_buyq INT COMMENT '주문가능매수수량',
    pred_sellq INT COMMENT '주문가능매도수량',
    tdy_buyq INT COMMENT '당일매수수량',
    tdy_sellq INT COMMENT '당일매도수량',
    raw_json TEXT COMMENT '원본 JSON',

    UNIQUE KEY uk_holding (snapshot_date, stk_cd, loan_dt),
    INDEX idx_snapshot_date (snapshot_date),
    INDEX idx_stock_code (stk_cd),
    INDEX idx_holdings_account (account_id),
    INDEX idx_holdings_snapshot_stk (snapshot_date, stk_cd)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='보유종목 테이블';

-- ============================================================
-- Table 3: account_summary
-- Purpose: Account summary synced from Kiwoom API
-- ============================================================
CREATE TABLE account_summary (
    snapshot_date DATE PRIMARY KEY COMMENT '스냅샷 일자',
    aset_evlt_amt BIGINT COMMENT '자산평가금액 (주식)',
    tot_est_amt BIGINT COMMENT '총평가금액 (주식+예수금)',
    invt_bsamt BIGINT COMMENT '투자원금',

    -- Extended fields
    acnt_nm VARCHAR(100) COMMENT '계좌명',
    brch_nm VARCHAR(100) COMMENT '지점명',
    entr BIGINT COMMENT '입금',
    d2_entra BIGINT COMMENT 'D+2입금',
    tot_pur_amt BIGINT COMMENT '총매입금액',
    prsm_dpst_aset_amt BIGINT COMMENT '추정예탁자산',
    tot_grnt_sella BIGINT COMMENT '총융자금',
    tdy_lspft_amt BIGINT COMMENT '당일실현손익금액',
    lspft_amt BIGINT COMMENT '실현손익금액',
    tdy_lspft BIGINT COMMENT '당일실현손익',
    lspft2 BIGINT COMMENT '실현손익2',
    lspft BIGINT COMMENT '실현손익',
    tdy_lspft_rt DECIMAL(10, 4) COMMENT '당일실현손익률',
    lspft_ratio DECIMAL(10, 4) COMMENT '실현손익비율',
    lspft_rt DECIMAL(10, 4) COMMENT '실현손익률',
    return_code INT COMMENT 'API 응답코드',
    return_msg VARCHAR(500) COMMENT 'API 응답메시지',
    raw_json TEXT COMMENT '원본 JSON'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='계좌요약 테이블';

-- ============================================================
-- Table 4: daily_lots
-- Purpose: Store daily net position lots (LIFO tracking)
-- ============================================================
CREATE TABLE daily_lots (
    lot_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL COMMENT '종목코드',
    stock_name VARCHAR(100) COMMENT '종목명',
    crd_class VARCHAR(10) NOT NULL COMMENT '신용구분 (CASH/CREDIT)',
    loan_dt VARCHAR(20) COMMENT '대출일자',
    trade_date DATE NOT NULL COMMENT '거래일자',
    net_quantity INT NOT NULL COMMENT '순매수량',
    avg_purchase_price DECIMAL(15, 2) NOT NULL COMMENT '평균매수가',
    total_cost DECIMAL(20, 2) NOT NULL COMMENT '총매수금액',

    -- Metrics (updated daily)
    holding_days INT COMMENT '보유일수',
    current_price DECIMAL(15, 2) COMMENT '현재가',
    unrealized_pnl DECIMAL(20, 2) COMMENT '미실현손익',
    unrealized_return_pct DECIMAL(10, 4) COMMENT '미실현수익률(%)',

    -- Lifecycle
    is_closed BOOLEAN DEFAULT FALSE COMMENT '종료여부',
    closed_date DATE COMMENT '종료일자',
    realized_pnl DECIMAL(20, 2) COMMENT '실현손익',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_daily_lot (stock_code, crd_class, loan_dt, trade_date),
    INDEX idx_stock_code (stock_code),
    INDEX idx_is_closed (is_closed),
    INDEX idx_trade_date (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='일별 순매수 lot 테이블';

-- ============================================================
-- Table 5: portfolio_snapshot
-- Purpose: Daily portfolio composition with weights and returns
-- ============================================================
CREATE TABLE portfolio_snapshot (
    snapshot_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    snapshot_date DATE NOT NULL COMMENT '스냅샷 일자',
    stock_code VARCHAR(20) NOT NULL COMMENT '종목코드',
    stock_name VARCHAR(100) COMMENT '종목명',
    crd_class VARCHAR(10) NOT NULL COMMENT '신용구분',

    -- Position metrics
    total_quantity INT NOT NULL COMMENT '총보유수량',
    avg_cost_basis DECIMAL(15, 2) COMMENT '평균단가',
    current_price DECIMAL(15, 2) COMMENT '현재가',
    market_value DECIMAL(20, 2) COMMENT '평가금액',
    total_cost DECIMAL(20, 2) COMMENT '총매수금액',

    -- Performance
    unrealized_pnl DECIMAL(20, 2) COMMENT '미실현손익',
    unrealized_return_pct DECIMAL(10, 4) COMMENT '미실현수익률(%)',
    portfolio_weight_pct DECIMAL(10, 4) COMMENT '포트폴리오 비중(%)',

    -- Portfolio total
    total_portfolio_value DECIMAL(20, 2) COMMENT '전체 포트폴리오 가치',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_snapshot (snapshot_date, stock_code, crd_class),
    INDEX idx_snapshot_date (snapshot_date),
    INDEX idx_stock_code (stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='포트폴리오 스냅샷 테이블';

-- ============================================================
-- Table 6: daily_portfolio_snapshot
-- Purpose: Daily asset status for TWR/MWR calculation
-- ============================================================
CREATE TABLE daily_portfolio_snapshot (
    snapshot_date DATE PRIMARY KEY COMMENT '스냅샷 일자',

    -- Total assets
    day_stk_asst BIGINT COMMENT '추정자산 (청산시 총자산)',
    tot_pur_amt BIGINT COMMENT '총매입금액',
    tot_evlt_amt BIGINT COMMENT '총평가금액',

    -- Daily cash flows
    ina_amt BIGINT COMMENT '당일 입금액',
    outa BIGINT COMMENT '당일 출금액',

    -- Daily transactions
    buy_amt BIGINT COMMENT '당일 매수금액',
    sell_amt BIGINT COMMENT '당일 매도금액',
    cmsn BIGINT COMMENT '수수료',
    tax BIGINT COMMENT '세금',

    -- Performance
    unrealized_pl BIGINT COMMENT '미실현손익',
    lspft_amt BIGINT COMMENT '실현손익',

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_snapshot_date (snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='일자별 포트폴리오 스냅샷 (수익률 계산용)';

-- ============================================================
-- Table 7: market_index
-- Purpose: KOSPI/KOSDAQ daily index data for benchmark comparison
-- ============================================================
CREATE TABLE market_index (
    index_date DATE PRIMARY KEY COMMENT '지수 일자',

    -- KOSPI
    kospi_close DECIMAL(10, 2) COMMENT 'KOSPI 종가',
    kospi_change DECIMAL(10, 2) COMMENT 'KOSPI 전일대비',
    kospi_change_pct DECIMAL(10, 4) COMMENT 'KOSPI 등락률(%)',

    -- KOSDAQ
    kosdaq_close DECIMAL(10, 2) COMMENT 'KOSDAQ 종가',
    kosdaq_change DECIMAL(10, 2) COMMENT 'KOSDAQ 전일대비',
    kosdaq_change_pct DECIMAL(10, 4) COMMENT 'KOSDAQ 등락률(%)',

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_index_date (index_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='시장지수(KOSPI/KOSDAQ) 일별 데이터';

-- ============================================================
-- Verification
-- ============================================================
SELECT 'Tables created successfully!' AS status;
SHOW TABLES;
