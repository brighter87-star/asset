#!/bin/bash
# Server execution script for daily lot tracking

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Activate virtual environment
source venv/bin/activate

# Run main pipeline
echo "=========================================="
echo "Asset Lot Tracking - $(date)"
echo "=========================================="

python3 main.py

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ Pipeline completed successfully"
else
    echo "✗ Pipeline failed with exit code: $EXIT_CODE"
fi

echo "=========================================="

exit $EXIT_CODE
