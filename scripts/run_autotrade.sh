#!/bin/bash
# Auto Trading 실행 스크립트 (Linux/Mac - tmux용)
#
# 사용법:
#   1. tmux 세션 생성: tmux new -s autotrade
#   2. 스크립트 실행: ./scripts/run_autotrade.sh
#   3. 세션 분리: Ctrl+B, D
#   4. 세션 재접속: tmux attach -t autotrade
#   5. 상태 확인: python3 auto_trade.py --status

cd "$(dirname "$0")/.."

# 가상환경 활성화
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

echo "========================================"
echo "  Auto Trading System Starting..."
echo "========================================"
echo ""
echo "Commands:"
echo "  Ctrl+C  : Stop trading"
echo "  Ctrl+B,D: Detach tmux (keeps running)"
echo ""

python3 auto_trade.py

echo ""
echo "Auto Trading System Stopped."
