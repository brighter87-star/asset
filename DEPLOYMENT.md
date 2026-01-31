# 서버 배포 가이드

## 준비사항

- 서버에 Python 3.8+ 설치
- 서버에 MariaDB/MySQL 설치
- Git 설치

## 1. Git Repository 생성 및 푸시

### 로컬에서

```bash
cd c:\Users\brigh\asset

# Git 초기화
git init

# 파일 추가
git add .

# 커밋
git commit -m "Initial commit: Daily lot tracking system"

# 원격 저장소 연결 (GitHub/GitLab 등)
git remote add origin <your-repository-url>

# 푸시
git push -u origin main
```

## 2. 서버에 배포

### 서버 접속

```bash
ssh brighter87@your-server
```

### 프로젝트 클론

```bash
cd ~/Projects
git clone <your-repository-url> asset
cd asset
```

### Python 가상환경 생성

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 환경 변수 설정

```bash
# .env 파일 생성
cat > .env << 'EOF'
# Kiwoom API (기존 assetmanager와 동일)
APP_KEY=your_app_key
SECRET_KEY=your_secret_key
BASE_URL=https://api.kiwoom.com
SOCKET_URL=wss://api.kiwoom.com:10000/api/dostk/websocket
ACNT_API_ID=kt00004

# Database (asset DB)
DB_HOST=localhost
DB_USER=brighter87
DB_PASSWORD=your_password
DB_NAME=asset

# Trading database (for sync)
TRADING_DB_NAME=trading
EOF

# 권한 설정
chmod 600 .env
```

## 3. 데이터베이스 생성

### MariaDB 접속

```bash
mysql -u brighter87 -p
```

### asset 데이터베이스 생성

```sql
CREATE DATABASE IF NOT EXISTS asset DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE asset;
```

### 테이블 생성

서버에서:

```bash
python setup_database.py
```

또는 직접:

```bash
mysql -u brighter87 -p asset < db/schema.sql
```

## 4. 초기 데이터 동기화

### trading DB에서 asset DB로 데이터 복사

```bash
python -c "
from services.data_sync_service import sync_all
sync_all(start_date=None, snapshot_date=None)
"
```

## 5. Lot 생성 및 분석 실행

```bash
python main.py
```

## 6. Cron 설정 (일별 자동 실행)

```bash
crontab -e
```

다음 라인 추가:

```cron
# 매일 오후 6시에 실행 (장 마감 후)
0 18 * * * cd /home/brighter87/Projects/asset && /home/brighter87/Projects/asset/venv/bin/python main.py >> /home/brighter87/Projects/asset/logs/daily_run.log 2>&1
```

로그 디렉토리 생성:

```bash
mkdir -p logs
```

## 7. 검증

### 데이터 확인

```bash
# Python으로
python -c "
from db.connection import get_connection
conn = get_connection()
with conn.cursor() as cur:
    cur.execute('SELECT COUNT(*) FROM daily_lots WHERE is_closed = FALSE')
    print(f'Open lots: {cur.fetchone()[0]}')
conn.close()
"
```

### MariaDB로

```sql
USE asset;

-- Lot 수 확인
SELECT COUNT(*) FROM daily_lots WHERE is_closed = FALSE;

-- 포트폴리오 스냅샷 확인
SELECT * FROM portfolio_snapshot
WHERE snapshot_date = CURDATE()
ORDER BY portfolio_weight_pct DESC;
```

## 8. 업데이트

서버에서 최신 코드 가져오기:

```bash
cd ~/Projects/asset
git pull origin main

# 새 패키지가 추가되었다면
source venv/bin/activate
pip install -r requirements.txt

# 스키마 변경이 있다면
python setup_database.py
```

## 디렉토리 구조

```
~/Projects/asset/
├── main.py                    # 메인 실행 파일
├── db/
│   ├── schema.sql
│   └── connection.py
├── services/
│   ├── data_sync_service.py
│   ├── lot_service.py
│   └── portfolio_service.py
├── config/
│   └── settings.py
├── utils/
│   ├── parsers.py
│   ├── normalize.py
│   └── krx_calendar.py
├── venv/                      # 가상환경
├── logs/                      # 로그 파일
├── .env                       # 환경 변수 (git에 커밋 안됨)
└── requirements.txt
```

## 문제 해결

### 데이터베이스 연결 실패

```bash
# MariaDB 서비스 상태 확인
sudo systemctl status mariadb

# 재시작
sudo systemctl restart mariadb
```

### 권한 문제

```sql
-- MariaDB에서
GRANT ALL PRIVILEGES ON asset.* TO 'brighter87'@'localhost';
FLUSH PRIVILEGES;
```

### Python 패키지 오류

```bash
# 가상환경 재생성
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
