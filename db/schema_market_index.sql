-- Market Index table for KOSPI/KOSDAQ daily data
-- Used for comparing portfolio performance against market benchmarks

USE asset;

CREATE TABLE IF NOT EXISTS market_index (
    index_date DATE PRIMARY KEY COMMENT '지수 일자',

    -- KOSPI (코스피)
    kospi_close DECIMAL(10, 2) COMMENT 'KOSPI 종가',
    kospi_change DECIMAL(10, 2) COMMENT 'KOSPI 전일대비',
    kospi_change_pct DECIMAL(10, 4) COMMENT 'KOSPI 등락률(%)',

    -- KOSDAQ (코스닥)
    kosdaq_close DECIMAL(10, 2) COMMENT 'KOSDAQ 종가',
    kosdaq_change DECIMAL(10, 2) COMMENT 'KOSDAQ 전일대비',
    kosdaq_change_pct DECIMAL(10, 4) COMMENT 'KOSDAQ 등락률(%)',

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_index_date (index_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='시장지수(KOSPI/KOSDAQ) 일별 데이터';
