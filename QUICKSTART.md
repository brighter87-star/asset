# Asset Management System - Quick Start

## Git 업로드 전 체크리스트

```bash
# 1. .env 파일이 Git에서 제외되었는지 확인
git status

# 2. .env.example이 있는지 확인
ls .env.example

# 3. Git에 추가할 파일들 확인
git add .
git status

# 4. 커밋 및 푸시
git commit -m "Initial commit: asset management system"
git push origin main
```

⚠️ **중요**: `.env` 파일은 절대 Git에 올리지 마세요! (API 키가 포함되어 있습니다)

## 서버에서 실행 (요약)

```bash
# 1. 클론
git clone <your-repo-url> ~/asset
cd ~/asset

# 2. 가상환경 및 패키지 설치
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. .env 파일 생성 (중요!)
cp .env.example .env
nano .env  # 실제 API 키와 DB 정보 입력

# 4. 데이터베이스 스키마 적용
mysql -u user -p asset < db/schema.sql

# 5. 데이터베이스 컬럼 추가
python add_columns_to_server.py

# 6. 테스트 실행
python sync_current_data.py

# 7. Cron 설정 (선택사항)
crontab -e
# 추가: 0 16 * * * cd ~/asset && ~/asset/venv/bin/python sync_current_data.py >> ~/asset/logs/sync.log 2>&1
mkdir -p ~/asset/logs
```

## 주요 스크립트

| 스크립트 | 용도 | 실행 예시 |
|---------|-----|----------|
| `sync_current_data.py` | 현재 잔고 및 보유종목 동기화 | `python sync_current_data.py` |
| `main.py` | 전체 거래내역 동기화 및 lot 구성 | `python main.py` |
| `rebuild_lots.py` | daily_lots 재구성 | `python rebuild_lots.py` |
| `check_trade_history.py` | 거래내역 확인 | `python check_trade_history.py` |
| `compare_with_kiwoom.py` | 키움 계좌와 비교 | `python compare_with_kiwoom.py` |

## 일일 작업 흐름

```bash
# 가상환경 활성화
cd ~/asset
source venv/bin/activate

# 데이터 동기화
python sync_current_data.py

# 결과 확인
python check_trade_history.py
```

## 문제 발생 시

```bash
# 로그 확인
tail -100 ~/asset/logs/sync.log

# 데이터베이스 연결 테스트
mysql -u user -p asset -e "SELECT COUNT(*) FROM holdings"

# Python 환경 확인
which python
python --version
pip list | grep PyMySQL
```
