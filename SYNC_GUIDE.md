# 원격 데이터 동기화 가이드

## 1단계: SSH 터널 설정

새 터미널 창을 열고 SSH 터널을 실행합니다:

```bash
ssh -L 3307:localhost:3306 brighter87@your-server-address
```

**참고:**
- `3307`: 로컬 포트 (임의로 지정 가능)
- `3306`: 서버의 MySQL 포트
- `your-server-address`: 실제 서버 주소로 변경

이 터미널은 동기화가 끝날 때까지 **열어두세요**.

## 2단계: 데이터 동기화 실행

새 터미널 창에서:

```bash
cd c:\Users\brigh\asset
.\venv\Scripts\python.exe sync_from_remote.py
```

이 스크립트는 다음을 수행합니다:
1. 기존 샘플 데이터 삭제
2. 원격 `trading` 데이터베이스에서 데이터 가져오기:
   - 모든 거래 내역 (`account_trade_history`)
   - 오늘자 보유 종목 (`holdings`)
   - 오늘자 계좌 요약 (`account_summary`)
3. 로컬 `asset` 데이터베이스에 저장

## 3단계: Lot 생성 및 분석

동기화가 완료되면 실제 데이터로 lot을 생성합니다:

```bash
.\venv\Scripts\python.exe test_pipeline.py
```

결과로 다음을 확인할 수 있습니다:
- 일별 lot 목록 (보유기간, 수익률)
- 포트폴리오 구성 (종목별 비중)

## 4단계: 데이터 확인

MySQL 클라이언트로 직접 확인:

```sql
-- 모든 오픈 lot
SELECT * FROM daily_lots WHERE is_closed = FALSE;

-- 포트폴리오 현황
SELECT * FROM portfolio_snapshot WHERE snapshot_date = CURDATE();

-- 거래 내역
SELECT * FROM account_trade_history ORDER BY trade_date DESC LIMIT 20;
```

## 증분 동기화

이미 데이터가 있고 최근 데이터만 추가하고 싶다면, `sync_from_remote.py`를 수정:

```python
# 전체 동기화
trades_count = sync_trade_history(conn_local, conn_remote, start_date=None)

# 최근 7일만 동기화 (예시)
trades_count = sync_trade_history(conn_local, conn_remote, start_date="2026-01-24")
```

## 문제 해결

### "Connection failed" 에러
- SSH 터널이 실행 중인지 확인
- 서버 주소와 포트 번호 확인
- MySQL 서버가 실행 중인지 확인

### "Access denied" 에러
- `sync_from_remote.py`의 비밀번호 확인
- 사용자 권한 확인

### 빈 데이터
- 서버의 `trading` 데이터베이스에 데이터가 있는지 확인
- 날짜 필터 확인 (오늘자 데이터가 없을 수 있음)
