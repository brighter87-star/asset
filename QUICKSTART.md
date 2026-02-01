# Asset Management System - Quick Start

## Git 업로드 전 체크리스트

```bash
# 1. .gitignore 확인
cat .gitignore

# 2. settings.py가 Git에서 제외되었는지 확인
git status

# 3. settings.py.example이 있는지 확인
ls config/settings.py.example

# 4. Git에 추가할 파일들 확인
git add .
git status

# 5. 커밋 및 푸시
git commit -m "Initial commit: asset management system"
git push origin main
```

## 서버에서 실행 (요약)

```bash
# 1. 클론
git clone <your-repo-url> ~/asset
cd ~/asset

# 2. 가상환경 및 패키지 설치
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 설정 파일 생성
cp config/settings.py.example config/settings.py
nano config/settings.py  # 실제 값으로 수정

# 4. 데이터베이스 스키마 적용
mysql -u user -p asset < db/schema.sql

# 5. 테스트 실행
python sync_current_data.py

# 6. Cron 설정 (선택사항)
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
