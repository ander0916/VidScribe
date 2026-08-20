#!/bin/bash
# VidScribe Lightning Studio 環境安裝
set -e
cd "$(dirname "$0")/.."

echo "=== 安裝系統依賴 ==="
apt-get update -qq
apt-get install -y -qq ffmpeg > /dev/null

echo "=== 安裝 Python 套件 ==="
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.lock.txt

echo "=== 安裝完成 ==="
echo "執行 lightning/start.sh 啟動伺服器"
