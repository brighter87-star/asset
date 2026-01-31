# Asset Management System

일별 Lot 추적 및 포트폴리오 분석 시스템

## 개요

이 시스템은 키움 API로부터 수집한 거래 데이터를 기반으로:
1. **일별 순매수 Lot 구성**: 하루 중 순매수량을 lot으로 구성
2. **보유기간 및 수익률 추적**: 각 lot의 보유일수, 미실현 손익률 계산
3. **포트폴리오 분석**: 현재 보유 종목의 수익률 및 포트폴리오 비중 표시

## 설치

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경 변수 설정

`.env` 파일이 이미 assetmanager에서 복사되었습니다. 필요시 `DB_NAME`을 확인하세요:

```
DB_NAME=asset
```

### 3. 데이터베이스 생성

MySQL에 접속하여 스키마를 실행합니다:

```bash
mysql -u brighter87 -p < db/schema.sql
```

## 사용법

### 최초 실행 (전체 데이터 동기화)

```bash
python main.py
```

최초 실행 시:
- trading 데이터베이스의 모든 거래 내역을 동기화
- 전체 기간의 일별 lot 구성
- 현재가 기준으로 모든 lot 지표 업데이트
- 오늘 날짜 포트폴리오 스냅샷 생성

### 일별 실행 (증분 처리)

`main.py`의 `construct_daily_lots` 호출 부분을 수정:

```python
# 전체 기간 처리 (최초 실행)
construct_daily_lots(conn, start_date=None, end_date=None)

# 증분 처리 (일별 실행)
construct_daily_lots(conn, start_date=yesterday, end_date=today)
```

## 주요 기능

### 1. 일별 Lot 조회

```sql
-- 모든 오픈 lot을 수익률 순으로 조회
SELECT
    stock_code,
    trade_date,
    net_quantity,
    avg_purchase_price,
    current_price,
    holding_days,
    unrealized_return_pct,
    unrealized_pnl
FROM daily_lots
WHERE is_closed = FALSE
ORDER BY unrealized_return_pct DESC;
```

### 2. 종목별 포지션 요약

```sql
-- 종목별 집계 정보 (여러 lot 합산)
SELECT
    stock_code,
    COUNT(*) as num_lots,
    SUM(net_quantity) as total_shares,
    SUM(total_cost) / SUM(net_quantity) as avg_cost_basis,
    SUM(unrealized_pnl) as total_unrealized_pnl,
    (SUM(unrealized_pnl) / SUM(total_cost) * 100) as position_return_pct
FROM daily_lots
WHERE is_closed = FALSE
GROUP BY stock_code
ORDER BY position_return_pct DESC;
```

### 3. 포트폴리오 스냅샷 조회

```sql
-- 현재 포트폴리오 구성 (비중 순)
SELECT
    stock_code,
    total_quantity,
    current_price,
    market_value,
    unrealized_return_pct,
    portfolio_weight_pct
FROM portfolio_snapshot
WHERE snapshot_date = CURDATE()
ORDER BY portfolio_weight_pct DESC;
```

## 데이터 흐름

```
trading DB (기존)
    ↓
[데이터 동기화]
    ↓
asset DB
    ├─ account_trade_history (거래 내역)
    ├─ holdings (현재 보유)
    └─ account_summary (계좌 요약)
    ↓
[일별 Lot 구성]
    ↓
daily_lots 테이블
    ↓
[지표 업데이트]
    ↓
daily_lots (현재가, 수익률 업데이트)
    ↓
[포트폴리오 스냅샷]
    ↓
portfolio_snapshot 테이블
```

## 프로젝트 구조

```
asset/
├── main.py                    # 메인 파이프라인
├── db/
│   ├── schema.sql            # 데이터베이스 스키마
│   └── connection.py         # DB 연결 관리
├── config/
│   └── settings.py           # 설정 관리
├── services/
│   ├── data_sync_service.py  # 데이터 동기화
│   ├── lot_service.py        # Lot 구성 및 관리
│   └── portfolio_service.py  # 포트폴리오 분석
└── utils/
    ├── parsers.py            # 데이터 파싱
    ├── normalize.py          # 데이터 정규화
    └── krx_calendar.py       # KRX 거래일 확인
```

## 핵심 로직

### LIFO Lot 차감

순매도일(매도량 > 매수량)의 경우, 가장 최근에 매수한 lot부터 차감합니다:

```python
# LIFO: Last In First Out
# 가장 최근 lot (trade_date DESC)부터 순서대로 차감
# 완전 매도 시 is_closed=TRUE 설정
```

### 일별 순매수량 계산

```python
net_quantity = SUM(매수량) - SUM(매도량)

if net_quantity > 0:
    # 새 lot 생성
    avg_price = SUM(매수금액) / SUM(매수량)
elif net_quantity < 0:
    # 기존 lot LIFO 차감
else:
    # 균형일 - 변경 없음
```

## 검증

### 데이터 무결성 확인

```sql
-- 1. lot 수량과 holdings 수량 일치 확인
SELECT
    h.stk_cd,
    h.rmnd_qty as holdings_qty,
    COALESCE(SUM(dl.net_quantity), 0) as lots_qty
FROM holdings h
LEFT JOIN daily_lots dl ON h.stk_cd = dl.stock_code
    AND h.crd_class = dl.crd_class
    AND dl.is_closed = FALSE
    AND h.snapshot_date = CURDATE()
GROUP BY h.stk_cd, h.rmnd_qty, h.crd_class
HAVING holdings_qty != lots_qty;

-- 2. 포트폴리오 총액 확인
SELECT
    SUM(market_value) as portfolio_total,
    MAX(total_portfolio_value) as expected_total
FROM portfolio_snapshot
WHERE snapshot_date = CURDATE();
```

## 참고사항

- **데이터베이스 분리**: asset DB는 trading DB와 별도로 운영
- **현재가 출처**: holdings.cur_prc (API에서 일별 업데이트)
- **포트폴리오 가치**: account_summary.aset_evlt_amt 사용 (2일 지연 있음)
- **LIFO 일관성**: 기존 lot_matches (거래 단위 LIFO)와 동일한 로직 적용

## 향후 개선 사항

- [ ] 실시간 현재가 업데이트
- [ ] 배당금 추적 테이블 추가
- [ ] 주식 분할 처리 로직 추가
- [ ] 증분 처리 최적화 (일별 실행 시)
- [ ] 웹 대시보드 구축
