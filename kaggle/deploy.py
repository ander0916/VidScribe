"""
VidScribe Kaggle 部署腳本
在 Kaggle Notebook 中執行此腳本即可啟動後端並建立公開連線

使用方法：
1. 建立 Kaggle Notebook（選 GPU：T4 或 P100）
2. 上傳此腳本或整個專案
3. 執行此腳本
"""

import subprocess
import sys
import os

# ===== 第 1 步：安裝依賴 =====
print("=== 安裝系統依賴 ===")
subprocess.run(["apt-get", "update", "-qq"], capture_output=True)
subprocess.run(["apt-get", "install", "-y", "-qq", "ffmpeg"], capture_output=True)

print("=== 安裝 Python 套件 ===")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ngrok"], capture_output=True)

# 安裝 VidScribe 後端依賴
req_file = "backend/requirements.lock.txt"
if os.path.exists(req_file):
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", req_file])

# ===== 第 2 步：設定 ngrok =====
print("=== 設定 ngrok ===")
from pyngrok import ngrok
from pyngrok.installer import get_ngrok_bin

# ngrok 免費版可以直接用，不需要 token
# 如果你有 ngrok token，取消下面的註釋：
# ngrok.set_auth_token("YOUR_NGROK_TOKEN")

# ===== 第 3 啟動 FastAPI 後端 =====
print("=== 啟動 VidScribe 後端 ===")

# 設定環境變數
os.environ["VIDSCRIBE_HOST"] = "0.0.0.0"
os.environ["VIDSCRIBE_PORT"] = "8765"
os.environ["VIDSCRIBE_LANG"] = "zh"

# 啟動 ngrok 隧道
public_url = ngrok.connect(8765)
print(f"\n{'='*50}")
print(f"✅ 公開網址: {public_url}")
print(f"{'='*50}")
print(f"\n請將此 URL 設為前端的 VITE_API_BASE")
print(f"然後重新建構並部署前端到 Cloudflare Pages\n")

# 啟動 uvicorn（在背景）
import uvicorn
import threading

def run_server():
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8765)

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

print("✅ 伺服器已啟動！")
print("保持此 Notebook 運行中...\n")

# 保持運行
import time
while True:
    time.sleep(60)
