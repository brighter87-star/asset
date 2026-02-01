#!/bin/bash
# Server setup script for asset management system
# Run this ONCE on a new server
#
# Usage:
#   chmod +x cron/setup_server.sh
#   ./cron/setup_server.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "========================================"
echo "Asset Management Server Setup"
echo "========================================"

cd "$PROJECT_DIR"

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "[ERROR] .env file not found!"
    echo "Please create .env file with your credentials."
    echo "See .env.example for template."
    exit 1
fi

# Create virtual environment if not exists
if [ ! -d "venv" ]; then
    echo "[1/4] Creating virtual environment..."
    python3 -m venv venv
else
    echo "[1/4] Virtual environment already exists"
fi

# Activate and install dependencies
echo "[2/4] Installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt

# Run initial backfill
echo "[3/4] Running initial backfill..."
python cron/initial_backfill.py

# Setup cron
echo "[4/4] Setting up cron..."
CRON_CMD="35 6 * * 1-5 cd $PROJECT_DIR && $PROJECT_DIR/venv/bin/python cron/daily_sync.py >> /var/log/asset_sync.log 2>&1"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "daily_sync.py"; then
    echo "Cron job already exists"
else
    # Add cron job
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    echo "Cron job added: runs at 15:35 KST (06:35 UTC) on weekdays"
fi

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "Cron schedule: Mon-Fri at 15:35 KST"
echo "Log file: /var/log/asset_sync.log"
echo ""
echo "Manual commands:"
echo "  python cron/daily_sync.py        # Run daily sync"
echo "  python cron/daily_sync.py --date 2026-01-30  # Sync specific date"

deactivate
