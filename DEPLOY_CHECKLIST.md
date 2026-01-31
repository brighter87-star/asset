# 서버 배포 체크리스트

## 로컬 작업

- [ ] Git repository 생성
  ```bash
  cd c:\Users\brigh\asset
  git init
  git add .
  git commit -m "Initial commit: Daily lot tracking system"
  ```

- [ ] GitHub/GitLab에 원격 저장소 생성

- [ ] 원격 저장소에 푸시
  ```bash
  git remote add origin <repository-url>
  git push -u origin main
  ```

## 서버 작업

### 1. 환경 준비

- [ ] 서버 접속
  ```bash
  ssh brighter87@your-server
  ```

- [ ] 필수 패키지 확인
  ```bash
  python3 --version  # Python 3.8+
  mysql --version    # MariaDB/MySQL
  git --version
  ```

### 2. 프로젝트 설치

- [ ] 프로젝트 클론
  ```bash
  cd ~/Projects
  git clone <repository-url> asset
  cd asset
  ```

- [ ] 가상환경 생성
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  pip install -r requirements.txt
  ```

- [ ] .env 파일 생성 (assetmanager/.env 참고)
  ```bash
  cp ~/Projects/assetmanager/.env .env
  # DB_NAME을 asset으로 변경
  sed -i 's/DB_NAME=trading/DB_NAME=asset/' .env
  ```

### 3. 데이터베이스 설정

- [ ] asset 데이터베이스 생성
  ```bash
  mysql -u brighter87 -p -e "CREATE DATABASE IF NOT EXISTS asset DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
  ```

- [ ] 테이블 생성
  ```bash
  python setup_database.py
  ```

- [ ] 초기 데이터 동기화
  ```bash
  python -c "from services.data_sync_service import sync_all; sync_all()"
  ```

### 4. 첫 실행

- [ ] 메인 파이프라인 실행
  ```bash
  python main.py
  ```

- [ ] 결과 확인
  ```bash
  mysql -u brighter87 -p asset -e "SELECT COUNT(*) as lot_count FROM daily_lots WHERE is_closed = FALSE;"
  ```

### 5. 자동화 설정

- [ ] 실행 스크립트 권한 설정
  ```bash
  chmod +x run_server.sh
  ```

- [ ] 로그 디렉토리 생성
  ```bash
  mkdir -p logs
  ```

- [ ] Cron 작업 등록
  ```bash
  crontab -e
  ```

  추가할 내용:
  ```
  0 18 * * * cd ~/Projects/asset && ./run_server.sh >> logs/daily_run.log 2>&1
  ```

- [ ] Cron 등록 확인
  ```bash
  crontab -l
  ```

## 검증

### 데이터 검증

- [ ] Lot 데이터 확인
  ```sql
  USE asset;
  SELECT stock_code, COUNT(*) as lots, SUM(net_quantity) as total_qty
  FROM daily_lots WHERE is_closed = FALSE
  GROUP BY stock_code
  ORDER BY total_qty DESC LIMIT 10;
  ```

- [ ] 포트폴리오 스냅샷 확인
  ```sql
  SELECT * FROM portfolio_snapshot
  WHERE snapshot_date = CURDATE()
  ORDER BY portfolio_weight_pct DESC
  LIMIT 10;
  ```

### 성능 확인

- [ ] 실행 시간 체크
  ```bash
  time python main.py
  ```

- [ ] 로그 확인
  ```bash
  tail -f logs/daily_run.log
  ```

## 완료!

모든 체크박스가 완료되면 서버 배포 완료입니다.

## 일일 모니터링

```bash
# 로그 확인
tail -20 ~/Projects/asset/logs/daily_run.log

# 최신 데이터 확인
mysql -u brighter87 -p asset -e "
SELECT
    MAX(snapshot_date) as latest_snapshot,
    COUNT(*) as total_positions
FROM portfolio_snapshot;"
```
