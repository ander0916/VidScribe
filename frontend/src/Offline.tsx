import Brand from "./Brand";

export default function Offline() {
  return (
    <div className="page offline-page">
      <header className="topbar">
        <Brand />
      </header>
      <main className="offline-main">
        <div className="offline-icon">💤</div>
        <h1 className="offline-title">服務暫時離線</h1>
        <p className="offline-desc">
          後端伺服器目前無法連線。
          <br />
          可能是主機正在關機或重啟中。
        </p>
        <div className="offline-divider" />
        <p className="offline-hint">
          如果你是管理員，請確認本機後端已啟動且 Tunnel 正常運行。
        </p>
        <button
          className="offline-retry"
          onClick={() => window.location.reload()}
        >
          重新整理頁面
        </button>
      </main>
    </div>
  );
}
