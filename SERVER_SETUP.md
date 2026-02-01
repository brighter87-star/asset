# Asset Management System - Server Setup Guide

## 1. 서버 준비 (Ubuntu/Debian 기준)

```bash
# Python 3.10+ 설치 확인
python3 --version

# pip 설치
sudo apt-get update
sudo apt-get install python3-pip python3-venv

# MySQL 클라이언트 라이브러리 설치
sudo apt-get install default-libmysqlclient-dev build-essential
```

## 2. 프로젝트 클론

```bash
cd ~
git clone <your-repo-url> asset
cd asset
```

## 3. 가상환경 설정

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 4. 설정 파일 생성

```bash
# settings.py 생성 (템플릿에서 복사)
cp config/settings.py.example config/settings.py

# 실제 값으로 수정
nano config/settings.py
```

필수 설정 항목:
- `DB_HOST`: MySQL 서버 주소
- `DB_USER`: MySQL 사용자명
- `DB_PASSWORD`: MySQL 비밀번호
- `DB_NAME`: 데이터베이스 이름 (asset)
- `BASE_URL`: Kiwoom API URL
- `APP_KEY`: Kiwoom App Key
- `SECRET_KEY`: Kiwoom Secret Key
- `ACNT_API_ID`: 계좌 API ID

## 5. 데이터베이스 설정

```bash
# MySQL에 접속하여 데이터베이스 생성
mysql -u root -p

# MySQL 쿼리
CREATE DATABASE IF NOT EXISTS asset DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON asset.* TO 'your_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;

# 스키마 적용
mysql -u your_user -p asset < db/schema.sql
```

## 6. 실행 테스트

```bash
# 가상환경 활성화
source venv/bin/activate

# 현재 데이터 동기화 테스트
python sync_current_data.py
```

## 7. 정기 실행 설정 (Cron)

매일 자동으로 데이터를 수집하려면 cron 설정:

```bash
# crontab 편집
crontab -e

# 다음 라인 추가 (매일 오후 4시 실행)
0 16 * * * cd /home/your_user/asset && /home/your_user/asset/venv/bin/python sync_current_data.py >> /home/your_user/asset/logs/sync.log 2>&1

# 로그 디렉토리 생성
mkdir -p ~/asset/logs
```

cron 스케줄 예시:
- `0 16 * * *` - 매일 오후 4시
- `0 9,16 * * *` - 매일 오전 9시, 오후 4시
- `*/30 9-15 * * 1-5` - 평일 9시-15시 사이 30분마다

## 8. 유지보수

### 데이터 동기화
```bash
cd ~/asset
source venv/bin/activate

# 거래 내역 동기화
python main.py

# 현재 보유 종목 및 잔고 동기화
python sync_current_data.py

# Lot 재구성
python rebuild_lots.py
```

### 로그 확인
```bash
# 최근 로그 확인
tail -f ~/asset/logs/sync.log

# 에러 로그 검색
grep ERROR ~/asset/logs/sync.log
```

### Git 업데이트
```bash
cd ~/asset
git pull
source venv/bin/activate
pip install -r requirements.txt
```

## 9. 보안 주의사항

⚠️ **절대로 Git에 커밋하면 안 되는 파일:**
- `config/settings.py` (실제 API 키 포함)
- `.env` 파일
- 로그 파일

✅ **Git에 포함되어야 하는 파일:**
- `config/settings.py.example` (템플릿)
- `.gitignore`
- 모든 Python 코드
- `requirements.txt`
- `README.md`, `SERVER_SETUP.md`

## 10. 문제 해결

### MySQL 연결 오류
```bash
# MySQL 서비스 상태 확인
sudo systemctl status mysql

# 연결 테스트
mysql -u your_user -p -h localhost
```

### Python 패키지 오류
```bash
# 가상환경 재생성
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### API 오류
- settings.py의 API 키 확인
- 네트워크 연결 확인
- API 서버 상태 확인
