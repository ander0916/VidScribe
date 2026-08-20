# VidScribe Lightning Studio 部署指南

## 快速開始

### 1. 建立 Lightning Studio 實例
1. 登入 https://lightning.ai/
2. 建立新的 Studio 實例
3. 選擇 GPU（建議 T4 或更好）

### 2. 上傳專案
在 Studio 終端機中執行：
```bash
git clone <你的 repo URL>
cd VidScribe-main
```

### 3. 安裝依賴
```bash
bash lightning/setup.sh
```

### 4. 啟動伺服器
```bash
bash lightning/start.sh
```

### 5. 獲取公開 URL
Lightning Studio 會自動提供公開 URL，格式為：
`https://<your-studio-id>.lightning.ai`

### 6. 更新前端
在本地電腦執行：
```bash
cd frontend
VITE_API_BASE="https://<your-studio-id>.lightning.ai" npm run build
npx wrangler pages deploy dist --project-name vidscribe
```

## 注意事項
- 首次辨識會自動下載 Whisper 模型（約 3GB）
- Studio 關閉後需重新執行 `start.sh`
- 確保 Studio 的公開 URL 已啟用
