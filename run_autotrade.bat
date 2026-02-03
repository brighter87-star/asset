@echo off
REM Auto Trading 실행 스크립트 (Windows)
REM
REM 사용법:
REM   run_autotrade.bat         - 트레이딩 시작
REM   run_autotrade.bat --status - 상태 확인
REM   run_autotrade.bat --test   - API 테스트

cd /d "%~dp0"

REM 가상환경 활성화
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

echo ========================================
echo   Auto Trading System (Kiwoom)
echo ========================================
echo.

if "%1"=="--status" (
    python auto_trade.py --status
) else if "%1"=="--test" (
    python auto_trade.py --test
) else if "%1"=="--ws-test" (
    python auto_trade.py --ws-test
) else (
    python auto_trade.py
)

echo.
pause
