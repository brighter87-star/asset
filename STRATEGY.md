# 자동매매 전략 문서

## 개요

추세추종 돌파 매매 전략 + 피라미딩
- 기준가 돌파 시 신용매수
- 수익 시 피라미딩, 손실 시 손절
- 최대 레버리지 120% (순자산 대비)

---

## 1. 진입 조건

### 1.1 돌파 진입 (Breakout Entry)
```
조건: 현재가 >= 기준가 (target_price)
주문: 신용매수, 현재가 + 3틱
```

### 1.2 갭업 진입 (Gap-Up Entry)
```
조건: 장 시작 시 시가 > 기준가
시간: 09:00 ~ 09:01 (첫 1분)
주문: 신용매수, 현재가 + 3틱
```

### 1.3 진입 제한
- 하루에 종목당 1회만 진입 (daily_triggers)
- 이미 보유 중인 종목은 추가 진입 안 함
- 레버리지 120% 초과 시 진입 안 함

---

## 2. 포지션 사이징

### 2.1 유닛 계산
```
1 UNIT = 순자산의 5%
매수금액 = UNIT / 2 (반유닛)
주문수량 = 매수금액 / (주문가격)
```

### 2.2 설정값 (watchlist.xlsx > settings)
| 키 | 기본값 | 설명 |
|---|---|---|
| UNIT | 1 | 매수 유닛 수 |
| TICK_BUFFER | 3 | 주문가 = 기준가 + 3틱 |
| STOP_LOSS_PCT | 7.0 | 손절률 (%) |
| MAX_LEVERAGE_PCT | 120.0 | 최대 레버리지 (%) |

---

## 3. 손절 조건

### 3.1 손절 트리거
```
조건: 현재가 <= 진입가 * (1 - STOP_LOSS_PCT / 100)
예시: 진입가 100,000원, 손절률 7% → 93,000원 이하 시 손절
```

### 3.2 손절 주문
```
주문가격: 현재가 - 3틱 (체결 확보)
주문유형: 지정가 매도
```

### 3.3 기존 보유종목
- 시스템 시작 시 `daily_lots` DB에서 보유종목 동기화
- lot별 평균매입가 기준으로 손절가 설정
- 수동 매매도 자동 반영 (main.py 동기화 통해)
- DB 실패 시 API fallback

---

## 4. 종가 청산 로직

### 4.1 적용 대상
```
당일 진입한 종목만 (daily_triggers에 있는 종목)
기존 보유종목은 종가 청산 대상 아님
```

### 4.2 실행 시간
```
장 마감 5분 전 (15:20 ~ 15:25 KST)
```

### 4.3 로직
```python
# 당일 진입 종목만 대상
if symbol not in daily_triggers:
    continue  # 기존 보유종목은 스킵

if 종가 > 진입가:
    # 수익 → 피라미딩 (반유닛 추가 매수)
    매수(현재가 + 3틱, 반유닛)
else:
    # 손실 → 전량 매도
    매도(현재가 - 3틱, 전량)
```

---

## 5. 주문 실행

### 5.1 매수 주문
```
API: POST /api/dostk/crdordr (신용매수)
API ID: kt10006
주문가격: 기준가 + (틱사이즈 * TICK_BUFFER)
주문유형: 지정가 (trde_tp: "0")
```

### 5.2 매도 주문
```
API: POST /api/dostk/ordr (일반매도)
API ID: kt00002
주문가격: 현재가 - (틱사이즈 * 3)
주문유형: 지정가
```

### 5.3 틱사이즈 테이블 (KRX)
| 가격대 | 틱사이즈 |
|---|---|
| ~ 2,000원 | 1원 |
| 2,000 ~ 5,000원 | 5원 |
| 5,000 ~ 20,000원 | 10원 |
| 20,000 ~ 50,000원 | 50원 |
| 50,000 ~ 200,000원 | 100원 |
| 200,000 ~ 500,000원 | 500원 |
| 500,000원 ~ | 1,000원 |

---

## 6. 모니터링

### 6.1 가격 조회
```
방식: REST API Polling (1초 간격)
API: ka10001 (개별종목 시세)
```

### 6.2 모니터링 대상
- watchlist.xlsx의 종목 (진입 감시)
- API 보유종목 (손절 감시)

### 6.3 화면 갱신
```
주기: 3초
내용: Watchlist 상태 + Holdings 손익
```

---

## 7. 중복 주문 방지

### 7.1 daily_triggers
```python
# 주문 시도 시점에 즉시 등록
daily_triggers[symbol] = {
    "entry_type": "breakout" | "gap_up",
    "entry_time": "2024-01-01T09:00:00",
    "status": "pending" | "success" | "order_failed" | "price_failed"
}
```

### 7.2 일간 리셋
```
시점: 자정 (날짜 변경 시)
동작: daily_triggers = {}
```

---

## 8. 파일 구조

```
c:\asset/
├── auto_trade.py          # 메인 실행 파일
├── watchlist.xlsx         # 감시종목 + 설정
├── .positions.json        # 포지션 상태 (자동 저장)
├── logs/                  # 거래 로그
│   └── trade_YYYYMMDD.log
├── services/
│   ├── kiwoom_service.py  # API 클라이언트
│   ├── monitor_service.py # 모니터링 로직
│   ├── order_service.py   # 주문/포지션 관리
│   ├── price_service.py   # 가격 조회 (REST Polling)
│   └── trade_logger.py    # 로깅
└── config/
    └── settings.py        # 환경변수 (.env)
```

---

## 9. 실행 방법

```bash
# 자동매매 실행
python auto_trade.py

# 상태 확인만
python auto_trade.py --status

# API 연결 테스트
python auto_trade.py --test

# 가격 API 테스트
python auto_trade.py --price-test
```

---

## 10. 해외주식 적용 (asset_us) 참고사항

### 변경 필요 항목
- API 엔드포인트 (한국투자증권 → 해외주식)
- 틱사이즈 테이블 (미국 시장은 $0.01)
- 거래 시간 (미국: 23:30 ~ 06:00 KST)
- 가격 단위 (USD, 소수점)
- 신용매수 → 일반매수 (해외주식은 신용 제한)

### 유지 항목
- 전략 로직 (돌파, 손절, 피라미딩)
- 포지션 사이징 (UNIT 기반)
- 모니터링 구조
