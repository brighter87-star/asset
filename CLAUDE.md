# Asset Management System - Claude Context

이 문서는 프로젝트의 핵심 로직과 구조를 정리하여 어디서든 대화를 이어갈 수 있게 합니다.

## 1. 트레이딩 전략 개요

### 기본 전략: 돌파 매수 + 피라미딩
1. **오전 돌파 매수** (8:00-9:10): watchlist 기준가 돌파 시 0.5 unit 매수
2. **종가 피라미딩** (17:50-20:00): 오늘 매수 종목이 수익 시 0.5 unit 추가
3. **종가 손절**: 오늘 매수 종목이 손실 시 전량 매도

### Unit 시스템
- 1 unit = 순자산의 5%
- 0.5 unit = 첫 매수 / 피라미딩 각각
- `settings.csv`에서 UNIT 값 조정 가능

---

## 2. 종가 로직 (execute_close_logic / execute_after_hours_close_logic)

### 시간대별 처리

| 시간대 | 대상 종목 | 처리 방식 |
|--------|----------|----------|
| **17:50-18:00** | non-NXT 종목 | 시간외단일가 (trde_tp="62") |
| **19:55-20:00** | NXT 가능 종목 | NXT 시장 지정가 |

### 종목 분류별 처리 ⚠️ 중요

```
┌─────────────────────────────────────────────────────────────────┐
│                    모든 보유 종목                                │
├─────────────────────────────────────────────────────────────────┤
│  LIFO lot 진입가 기준 -7% 이하 → 해당 lot 손절                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                 오늘 매수 종목만 (daily_triggers)                │
├─────────────────────────────────────────────────────────────────┤
│  >0%  → 피라미딩 (0.5 unit 추가)                                │
│  <=0% → 오늘 lot 손절                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              기존 보유 종목 (오늘 매수 X)                         │
├─────────────────────────────────────────────────────────────────┤
│  -7% 미만 ~ 0% 사이 → 아무 조치 없음                             │
│  0% 이상           → 아무 조치 없음                             │
│  ⚠️ 오직 -7% 손절만 체크하고, 그 외에는 건드리지 않음!           │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. LIFO Lot 기반 손익 계산

### Lot이란?
- 같은 날 매수한 동일 종목을 하나의 "lot"으로 관리
- 매도 시 **LIFO (Last In First Out)**: 가장 최근 lot부터 차감

### 손절 기준
- `check_stop_loss()`: **LIFO lot 진입가** 기준 -7%
- `execute_close_logic()`: **LIFO lot 진입가** 기준 판단

### 관련 함수
- `get_latest_lot(conn, symbol)`: 가장 최근 open lot 조회
- `get_lots_lifo(conn, symbol)`: 모든 open lots LIFO 순서로 조회
- `_reduce_lots_lifo()`: LIFO 방식으로 lot 차감

---

## 4. NXT 거래 가능 여부 확인

```python
def is_nxt_tradable(self, symbol: str) -> bool:
    # NXT 가격 조회 후 price > 0이면 거래 가능
    # 결과는 당일 캐시됨
```

- NXT 가능: 19:55-20:00에 처리
- NXT 불가: 17:50-18:00 시간외단일가로 처리

---

## 5. 시간외단일가 주문

### API 파라미터
```python
body = {
    "dmst_stex_tp": "KRX",
    "stk_cd": stock_code,
    "ord_qty": str(quantity),
    "ord_uv": str(price),
    "trde_tp": "62",  # 시간외단일가
}
```

### 가격 제한
- 상한가: 종가 × 1.1
- 하한가: 종가 × 0.9
- 손절 시 하한가로 주문

---

## 6. DB 스키마 주요 테이블

### daily_lots
- 일별 순매수 lot 추적
- LIFO 손익 계산의 기반
- `is_closed`, `closed_date`, `realized_pnl` 관리

### portfolio_snapshot
- 일별 포트폴리오 구성
- `prsm_dpst_aset_amt` (추정자산) 기준 비중 계산

### daily_portfolio_snapshot
- Kiwoom API에서 동기화한 일별 자산 현황
- TWR/MWR 수익률 계산용

### account_trade_history
- 모든 체결 내역
- lot 구성의 원천 데이터

---

## 7. 주요 서비스 파일

| 파일 | 역할 |
|------|------|
| `services/monitor_service.py` | 자동매매 메인 로직, 종가 처리 |
| `services/order_service.py` | 주문 실행, 포지션 관리 |
| `services/lot_service.py` | LIFO lot 관리, 손익 계산 |
| `services/kiwoom_service.py` | Kiwoom API 통신 |
| `services/portfolio_service.py` | 포트폴리오 스냅샷 생성 |

---

## 8. 실행 방법

### 자동매매 시작
```bash
python auto_trade.py
```

### DB 초기화 (새 환경)
```bash
mysql -u root -p < db/init_all_tables.sql
python cron/initial_backfill.py --start-date 2025-12-11
```

### 일일 동기화 (cron)
```bash
python cron/daily_sync.py
```

---

## 9. 설정 파일

### watchlist.csv
```csv
ticker,name,target_price,max_units
005930,삼성전자,85000,2
```

### settings.csv
```csv
key,value
UNIT,1
TICK_BUFFER,3
STOP_LOSS_PCT,7
```

---

## 10. 최근 변경사항 (2026-02-05)

1. **종가 로직 LIFO lot 기반으로 변경**
   - 평균가 → LIFO lot 진입가 기준
   - 오늘 매수 종목만 피라미딩/손절

2. **시간외단일가 로직 추가**
   - non-NXT 종목: 17:50-18:00 처리
   - `trde_tp="62"` 사용
   - 하한가(종가×0.9)로 매도

3. **매도 API 파라미터 수정**
   - `ord_tp` → `trde_tp`
   - `ord_prc` → `ord_uv`
