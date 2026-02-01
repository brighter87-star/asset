-- Daily portfolio snapshot table
-- Records daily asset status including presumed asset, holdings, cash, and cash flows
-- Used for calculating time-weighted and money-weighted returns

USE asset;

CREATE TABLE IF NOT EXISTS daily_portfolio_snapshot (
    snapshot_date DATE PRIMARY KEY COMMENT '스냅샷 일자',

    -- Cash balances
    d2_entra BIGINT COMMENT 'D+2 예수금 (출금가능)',
    entr BIGINT COMMENT 'D+0 예수금',

    -- Total assets
    prsm_dpst_aset_amt BIGINT COMMENT '추정예탁자산 (청산시 총자산)',
    tot_est_amt BIGINT COMMENT '총추정금액',
    aset_evlt_amt BIGINT COMMENT '주식평가금액',
    tot_pur_amt BIGINT COMMENT '총매입금액',

    -- Margin/Credit
    tot_grnt_sella BIGINT COMMENT '총융자금',
    crd_int_npay_gold BIGINT COMMENT '신용이자미납금',

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
) COMMENT='일자별 포트폴리오 스냅샷';
