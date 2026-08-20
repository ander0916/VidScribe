# VideoSub 部署指南

## 方案一：本機 + Cloudflare Tunnel（最簡單）

### 前置需求
- Windows 10/11
- Python 3.13+
- ffmpeg
- Node.js（前端開發用，非必要）

### 步驟

```bash
# 1. 安裝依賴（首次）
setup.bat

# 2. 啟動後端 + Tunnel + 部署前端
start.bat
```

### 手動部署

```bash
# 啟動後端
.venv\Scripts\python.exe run.py

# 啟動 Cloudflare Tunnel（另一個終端機）
cloudflared tunnel --url http://localhost:8765

# 重建前端
cd frontend
VITE_API_BASE="https://<tunnel-url>" npm run build

# 部署到 Cloudflare Pages
npx wrangler pages deploy dist --project-name vidscribe
```

---

## 方案二：Kaggle + ngrok（免費 GPU）

### 步驟

1. 建立 Kaggle Notebook，選 GPU (T4)
2. 執行以下指令：

```python
!git clone https://github.com/ander0916/VidScribe.git VidScribe-main
%cd VidScribe-main
!pip install -q -r backend/requirements.lock.txt pyngrok
!apt-get update -qq && apt-get install -y -qq ffmpeg

import os, threading, time
from pyngrok import ngrok
import uvicorn

os.environ["VIDSCRIBE_HOST"] = "0.0.0.0"
os.environ["VIDSCRIBE_PORT"] = "8765"

public_url = ngrok.connect(8765)
print(f"公開網址: {public_url}")

threading.Thread(
    target=lambda: uvicorn.run("backend.main:app", host="0.0.0.0", port=8765),
    daemon=True
).start()

while True:
    time.sleep(60)
```

3. 拿到 ngrok URL 後，在本機更新前端：

```bash
cd frontend
VITE_API_BASE="<ngrok-url>" npm run build
npx wrangler pages deploy dist --project-name vidscribe
```

---

## 方案三：Lightning Studio

### 步驟

1. 登入 https://lightning.ai/
2. 建立 Studio 實例（選 GPU）
3. 在終端機執行：

```bash
git clone https://github.com/ander0916/VidScribe.git VidScribe-main
cd VidScribe-main
bash lightning/setup.sh
bash lightning/start.sh
```

4. 拿到 Studio URL 後，更新前端（同方案二步驟 3）

---

## 環境變數

| 變數 | 預設 | 說明 |
|------|------|------|
| `VIDSCRIBE_MODEL` | `large-v3` | Whisper 模型 |
| `VIDSCRIBE_LANG` | `zh` | 語言（`zh` 固定中文，`auto` 自動偵測）|
| `VIDSCRIBE_PORT` | `8765` | 服務埠 |
| `VIDSCRIBE_HOST` | `127.0.0.1` | 綁定位址（雲端部署設為 `0.0.0.0`）|
| `VIDSCRIBE_DATA` | `./projects` | 專案資料夾 |
| `VIDSCRIBE_MODELS` | `./models` | 模型資料夾 |
| `VIDSCRIBE_EXTRA_HOSTS` | - | 額外允許的 Host（逗號分隔）|
| `VIDSCRIBE_EXTRA_ORIGINS` | - | 額外允許的 Origin（逗號分隔）|

---

## 常見問題

### CORS 錯誤
確保後端啟動時帶有 `VIDSCRIBE_EXTRA_ORIGINS` 環境變數，包含你的前端網域。

### 模型下載失敗
設定 HuggingFace 鏡像站：
```bash
set HF_ENDPOINT=https://hf-mirror.com
```

### 關機後無法使用
本機方案需要保持電腦開機。如需 24/7 可用，請使用 Kaggle 或 Lightning Studio 方案。

---

## 架構

```
瀏覽器 → hsutools.kdns.fr (Cloudflare Pages)
    ↓ API
Cloudflare Tunnel → 本機後端 (127.0.0.1:8765)
    ↓
faster-whisper (GPU) + ffmpeg
```
