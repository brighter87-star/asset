#!/bin/bash
# Auto-restart trading bot when Python files change
# Usage: ./run_trading.sh

cd "$(dirname "$0")"

echo "=== Auto Trading Bot (Auto-Restart Mode) ==="
echo "Will restart automatically when .py files change"
echo ""

while true; do
    # Record modification times of Python files
    HASH_BEFORE=$(find . -name "*.py" -exec stat -c %Y {} \; 2>/dev/null | md5sum)

    # Run trading bot
    python3 auto_trade.py &
    PID=$!

    echo "[WRAPPER] Bot started with PID $PID"

    # Monitor for file changes while bot is running
    while kill -0 $PID 2>/dev/null; do
        sleep 5
        HASH_AFTER=$(find . -name "*.py" -exec stat -c %Y {} \; 2>/dev/null | md5sum)

        if [ "$HASH_BEFORE" != "$HASH_AFTER" ]; then
            echo ""
            echo "[WRAPPER] Python files changed! Restarting bot..."
            kill $PID 2>/dev/null
            sleep 2
            break
        fi
    done

    # Wait for process to fully exit
    wait $PID 2>/dev/null
    EXIT_CODE=$?

    echo "[WRAPPER] Bot exited with code $EXIT_CODE"

    # If killed by Ctrl+C (130), exit the wrapper too
    if [ $EXIT_CODE -eq 130 ] || [ $EXIT_CODE -eq 2 ]; then
        echo "[WRAPPER] Ctrl+C detected, exiting..."
        exit 0
    fi

    echo "[WRAPPER] Restarting in 3 seconds..."
    sleep 3
done
