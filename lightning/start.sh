#!/bin/bash
# VidScribe Lightning Studio 啟動腳本
set -e
cd "$(dirname "$0")/.."

HOST="${VIDSCRIBE_HOST:-0.0.0.0}"
PORT="${VIDSCRIBE_PORT:-8765}"

echo "VidScribe 啟動中: http://${HOST}:${PORT}"
python -c "
import uvicorn
import os
os.environ['VIDSCRIBE_HOST'] = '${HOST}'
uvicorn.run('backend.main:app', host='${HOST}', port=${PORT})
"
