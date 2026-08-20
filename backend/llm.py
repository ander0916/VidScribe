"""用使用者已安裝的 Claude Code CLI(走訂閱)做字幕錯字校正。

設計原則(見 SPEC 3.5):
- 指令自動尋路,找不到就整個功能隱藏,不影響其他功能
- 只送「行號+文字」,LLM 碰不到時間軸;回傳純 JSON 由程式端驗證
- 精簡呼叫:--system-prompt 換掉 Claude Code 預設 agent 環境
  (系統提示詞+工具+MCP 是每批 ~30k token/40+ 秒固定開銷的大宗,
  也會注入專案環境資訊造成誤傷;2026-08-20 實測單批 62s→16s)
- 不用 --json-schema:結構化輸出靠工具呼叫要多繞兩個 turn,
  且和自訂系統提示詞/--disallowedTools 衝突;改要求純 JSON+失敗重試一次
- 大批次呼叫+批次完成即可審(前端串流合併)
- 建議不自動套用,由前端 diff 審閱
"""

import json
import os
import shutil
import subprocess
import threading
import time
import traceback
from pathlib import Path

from . import storage

MODEL = os.environ.get("VIDSCRIBE_FIX_MODEL", "sonnet")
BATCH_CHARS = 4000  # 每批的字元預算
BATCH_LINES = 80
TIMEOUT = 300

PROMPT = """你是台灣的專業字幕校對員。最後面附上一段影片的字幕 JSON 陣列(繁體中文、台灣口語),每項有行號 i 與文字 t。
請找出並修正:
1. 語音辨識造成的同音錯字與選字錯誤(例:其美博物館→奇美博物館、發老→法老、在→再)
2. 中國用語改成台灣慣用語(例:視頻→影片、質量→品質、軟件→軟體)
3. 品牌與專有名詞的正確寫法與大小寫(例:youtube→YouTube、Ig→IG)
規則:
- 只回傳有修正的行,沒錯的行不要回傳
- 不可增刪或合併句子,不可改變句意
- 口語詞與語氣詞(嗯、啊、欸、就是、其實…)一律保留,不要書面化
- 字數盡量與原文相近,禁止重寫句子
- 標點維持原樣,不要新增句尾標點
用 changes 回傳:i 是原行號,t 是修正後的整行文字。整批都沒錯就回傳空的 changes。"""

# 走 --system-prompt(argv)必須壓成單行:多行參數經 npm 版 claude.cmd 轉手會截斷
SYSTEM_PROMPT = (
    PROMPT.replace("\n", " ")
    + ' 直接回傳純 JSON(不要 markdown 圍欄、不要任何其他文字),'
    + '格式:{"changes":[{"i":行號,"t":"修正後整行"}]}。'
)

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def find_claude() -> list[str] | None:
    path = shutil.which("claude")
    if not path:
        candidates = [
            Path.home() / ".local" / "bin" / "claude.exe",
            Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd",
        ]
        for c in candidates:
            if c.is_file():
                path = str(c)
                break
    if not path:
        return None
    # .cmd/.bat 無法被 CreateProcess 直接執行,要透過 cmd /c
    if path.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", path]
    return [path]


def _public_state(job: dict | None) -> dict:
    if job is None:
        return {"status": "idle"}
    return {k: job[k] for k in ("status", "total", "done", "suggestions", "error", "started_at")}


def _fix_file(pid: str):
    return storage.project_dir(pid) / "fix.json"


def _save_fix_file(pid: str, job: dict) -> None:
    """校正結果落地,伺服器重開也還原得回來。"""
    f = _fix_file(pid)
    tmp = f.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fp:
        json.dump(
            {
                "total": job.get("total", 1),
                "started_at": job.get("started_at"),
                "suggestions": job.get("suggestions", []),
            },
            fp,
            ensure_ascii=False,
        )
    os.replace(tmp, f)


def get_state(pid: str) -> dict:
    with _lock:
        job = _jobs.get(pid)
        if job is not None:
            return _public_state(job)
    f = _fix_file(pid)
    if f.is_file():
        try:
            with f.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
            return {
                "status": "done",
                "total": data.get("total", 1),
                "done": data.get("total", 1),
                "suggestions": data.get("suggestions", []),
                "error": None,
                "started_at": data.get("started_at"),
            }
        except (OSError, json.JSONDecodeError):
            pass
    return {"status": "idle"}


def cancel(pid: str) -> None:
    with _lock:
        job = _jobs.get(pid)
        if job and job["status"] == "running":
            job["cancel"] = True
        else:
            _jobs.pop(pid, None)
    _fix_file(pid).unlink(missing_ok=True)


def remove_suggestions(pid: str, items: list[dict]) -> None:
    """把審閱掉的建議(接受或略過)從清單移除,關機重開能從剩的繼續。

    用「移除哪幾條」而不是「整份清單覆蓋」:分析還在跑時工作執行緒
    同時在追加新批次的建議,覆蓋語意會把新到的蓋掉。
    """
    keys = {(str(s.get("id")), str(s.get("old"))) for s in items}
    with _lock:
        job = _jobs.get(pid)
        if job is not None:
            job["suggestions"] = [
                s for s in job["suggestions"] if (s["id"], s["old"]) not in keys
            ]
            if job["status"] == "running":
                return  # 進行中不落地,完成時 _run 會存最終清單
            remaining = list(job["suggestions"])
            holder = {
                "total": job.get("total", 1),
                "started_at": job.get("started_at"),
                "suggestions": remaining,
            }
        else:
            remaining = None
            holder = None
    if remaining is None:
        # 伺服器重啟後從 fix.json 接著審的情況
        f = _fix_file(pid)
        if not f.is_file():
            return
        try:
            with f.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError):
            return
        remaining = [
            s
            for s in data.get("suggestions", [])
            if (str(s.get("id")), str(s.get("old"))) not in keys
        ]
        holder = {
            "total": data.get("total", 1),
            "started_at": data.get("started_at"),
            "suggestions": remaining,
        }
    if remaining:
        _save_fix_file(pid, holder)
    else:
        _fix_file(pid).unlink(missing_ok=True)


def start(pid: str, ids: list[str] | None = None) -> dict:
    """啟動校正。ids 給定時只校正那些字幕(使用者自選範圍),否則整份。"""
    cmd = find_claude()
    if cmd is None:
        raise RuntimeError("找不到 claude 指令,請先安裝 Claude Code")
    segments = storage.load_subtitles(pid)["segments"]
    if not segments:
        raise RuntimeError("這個專案還沒有字幕")
    if ids is None:
        pick = range(len(segments))
    else:
        idset = set(ids)
        pick = [i for i, s in enumerate(segments) if s["id"] in idset]
        if not pick:
            raise RuntimeError("選取範圍內沒有字幕")

    batches: list[list[int]] = []
    cur: list[int] = []
    chars = 0
    for i in pick:
        cur.append(i)
        chars += len(segments[i]["text"])
        if len(cur) >= BATCH_LINES or chars >= BATCH_CHARS:
            batches.append(cur)
            cur, chars = [], 0
    if cur:
        batches.append(cur)

    job = {
        "status": "running",
        "total": len(batches),
        "done": 0,
        "suggestions": [],
        "error": None,
        "started_at": time.time(),
        "cancel": False,
    }
    with _lock:
        existing = _jobs.get(pid)
        if existing and existing["status"] == "running":
            raise RuntimeError("AI 校正已在進行中")
        _jobs[pid] = job

    threading.Thread(target=_run, args=(pid, cmd, segments, batches, job), daemon=True).start()
    return _public_state(job)


def _run_batch(cmd: list[str], segments: list[dict], indices: list[int]) -> list[dict]:
    payload = json.dumps(
        [{"i": i, "t": segments[i]["text"]} for i in indices], ensure_ascii=False
    )
    proc = subprocess.run(
        cmd
        + [
            "-p",
            "--output-format", "json",
            "--model", MODEL,
            "--system-prompt", SYSTEM_PROMPT,
            # 連「動態環境段落」也不要:模型看到工作目錄叫 VidScribe,
            # 會把字幕裡的「What's up!」改成「VidScribe!」(實測誤傷)
            "--exclude-dynamic-system-prompt-sections",
            # 不載使用者的 MCP servers/全域設定/工具:純文字任務用不到,
            # 少掉 ~30k token 的載入,單批快 4 倍(2026-08-20 實測)
            "--strict-mcp-config",
            "--setting-sources", "project",
            "--disallowedTools", "*",
        ],
        input=f"字幕內容:\n{payload}",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT,
        # 關掉 thinking:錯字校正是機械任務,延遲主因就是 thinking 的輸出量
        # (單批 13~16s→4~5s,且耗時不再隨思考量飄;2026-08-20 實測品質不變)
        env={**os.environ, "MAX_THINKING_TOKENS": "0"},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude 執行失敗:{(proc.stderr or proc.stdout).strip()[-300:]}")
    data = json.loads(proc.stdout)
    if data.get("is_error") or data.get("subtype") != "success":
        raise RuntimeError(f"claude 回傳錯誤:{str(data.get('result'))[:300]}")
    out = data.get("structured_output")  # 保險:未來若掛回 schema 也吃得下
    if not isinstance(out, dict):
        text = str(data.get("result", "")).strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        out = json.loads(text)
    changes = out.get("changes") or []

    valid = set(indices)
    suggestions = []
    for c in changes:
        i = c.get("i")
        new = (c.get("t") or "").strip()
        if i in valid and new and new != segments[i]["text"]:
            suggestions.append({"id": segments[i]["id"], "old": segments[i]["text"], "new": new})
    return suggestions


def _run(pid: str, cmd: list[str], segments: list[dict], batches: list[list[int]], job: dict) -> None:
    try:
        for indices in batches:
            if job["cancel"]:
                job["status"] = "canceled"
                return
            try:
                suggestions = _run_batch(cmd, segments, indices)
            except Exception:
                # 沒有 schema 強制,偶爾會拿到壞 JSON;重試一次,再失敗才放棄整輪
                traceback.print_exc()
                if job["cancel"]:
                    job["status"] = "canceled"
                    return
                suggestions = _run_batch(cmd, segments, indices)
            with _lock:
                job["suggestions"].extend(suggestions)
                job["done"] += 1
        job["status"] = "done"
        with _lock:
            holder = dict(job)  # 邊跑邊審會併發改 suggestions,鎖內拿一致的快照
        try:
            _save_fix_file(pid, holder)
        except OSError:
            traceback.print_exc()  # 存檔失敗不影響本次結果,只是重開伺服器會遺失
    except Exception as e:
        traceback.print_exc()
        job["status"] = "error"
        job["error"] = str(e)[:500]
