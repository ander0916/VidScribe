"""短片成品匯出:剪時間段 + 裁 9:16 + 燒字幕,一次一支排隊輸出。

沿用 burn.py 的做法:NVENC 失敗自動降級 x264、-progress pipe:1 回報進度、
stderr 導檔避免管線死鎖、cwd=專案目錄配裸檔名避開 Windows 濾鏡路徑跳脫。
剪段後音訊一律重編 aac(直接 copy 容易在非關鍵幀邊界出問題)。
"""

import re
import subprocess
import threading
import traceback

from . import burn, clips, config, exporter, storage

OUT_W, OUT_H = 1080, 1920
MARGIN_V_RATIO = 0.24  # 字幕避開 Shorts/Reels 底部 22% UI 區
ASS_NAME = "clip.ass"  # 單一佇列一次只跑一支,不會撞名

# (影像編碼器,)由快到慢;音訊固定 aac
ATTEMPTS = ["h264_nvenc", "libx264"]

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _scan_files(pid: str) -> list[str]:
    d = clips.clips_dir(pid)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.mp4") if re.fullmatch(r"[0-9a-f]{8}", p.stem))


def get_state(pid: str) -> dict:
    with _lock:
        job = _jobs.get(pid)
        state = (
            {k: job[k] for k in ("status", "current", "progress", "error")}
            | {"queue": list(job["queue"]), "done_ids": list(job["done_ids"])}
            if job
            else {
                "status": "idle",
                "queue": [],
                "current": None,
                "progress": 0.0,
                "done_ids": [],
                "error": None,
            }
        )
    state["files"] = _scan_files(pid)
    return state


def cancel(pid: str) -> None:
    with _lock:
        job = _jobs.get(pid)
        if job and job["status"] == "running":
            job["cancel"] = True
            job["queue"].clear()
            proc = job.get("proc")
            if proc is not None:
                try:
                    proc.kill()
                except OSError:
                    pass
        else:
            _jobs.pop(pid, None)


def start(pid: str, ids: list[str]) -> dict:
    meta = storage.load_project(pid)
    if meta is None:
        raise RuntimeError("找不到專案")
    if not meta.get("has_video"):
        raise RuntimeError("純音訊檔沒有畫面,無法匯出短片")
    known = {c["id"] for c in clips.load_clips(pid)}
    ids = [i for i in dict.fromkeys(ids)]  # 去重保序
    if not ids or not all(i in known for i in ids):
        raise RuntimeError("找不到指定的短片")
    media = storage.project_dir(pid) / meta["media_file"]
    if not media.is_file():
        raise RuntimeError("找不到媒體檔")

    with _lock:
        job = _jobs.get(pid)
        if job and job["status"] == "running":
            for i in ids:
                if i not in job["queue"] and i != job["current"]:
                    job["queue"].append(i)
            return get_state(pid)
        job = {
            "status": "running",
            "queue": list(ids),
            "current": None,
            "progress": 0.0,
            "done_ids": [],
            "error": None,
            "cancel": False,
            "proc": None,
        }
        _jobs[pid] = job

    threading.Thread(
        target=_run, args=(pid, meta["media_file"], job), daemon=True
    ).start()
    return get_state(pid)


def _build_vf(iw: int, ih: int, pan: float) -> str:
    """置中裁 9:16;pan ∈ [-1,1] 對應最左~最右。來源比 9:16 窄就改裁高、忽略 pan。"""
    frac = (max(-1.0, min(1.0, pan)) + 1) / 2
    if iw * 16 > ih * 9:  # 比 9:16 寬(一般橫式)
        crop = f"crop=w='2*floor(ih*9/32)':h=ih:x='(iw-ow)*{frac:.4f}':y=0"
    else:  # 已是直式或更窄:裁高置中
        crop = "crop=w=iw:h='2*floor(iw*8/9)':x=0:y='(ih-oh)/2'"
    return f"{crop},scale={OUT_W}:{OUT_H},setsar=1,ass={ASS_NAME}"


def _render_clip(pid: str, d, media_name: str, clip: dict, iw: int, ih: int, job: dict) -> None:
    start, end = float(clip["start"]), float(clip["end"])
    dur = end - start
    segments = storage.load_subtitles(pid)["segments"]
    # -ss 在 -i 前會把 PTS 重定為 0,字幕時間同步平移 -start
    rebased = [
        {
            "start": max(s["start"] - start, 0.0),
            "end": min(s["end"], end) - start,
            "text": s["text"],
        }
        for s in segments
        if s["end"] > start and s["start"] < end
    ]
    (d / ASS_NAME).write_text(
        exporter.to_ass(rebased, OUT_W, OUT_H, margin_v_ratio=MARGIN_V_RATIO),
        encoding="utf-8",
    )
    vf = _build_vf(iw, ih, float(clip.get("pan", 0.0)))
    out_rel = f"clips/{clip['id']}.mp4"
    err_file = d / "clip_err.txt"

    last_err = ""
    for vcodec in ATTEMPTS:
        if job["cancel"]:
            return
        args = [config.FFMPEG, "-y", "-v", "error", "-nostats", "-progress", "pipe:1",
                "-ss", f"{start:.3f}", "-i", media_name, "-t", f"{dur:.3f}",
                "-vf", vf, "-c:v", vcodec]
        if vcodec == "h264_nvenc":
            args += ["-preset", "p5", "-cq", "19"]
        else:
            args += ["-preset", "medium", "-crf", "19"]
        args += ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_rel]

        with err_file.open("w", encoding="utf-8") as ef:
            proc = subprocess.Popen(
                args, cwd=str(d), stdout=subprocess.PIPE, stderr=ef,
                text=True, encoding="utf-8", errors="replace",
            )
            job["proc"] = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                m = re.match(r"out_time=(\d+):(\d+):([\d.]+)", line.strip())
                if m and dur > 0:
                    t = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
                    job["progress"] = min(round(t / dur, 3), 0.99)
            proc.wait()
            job["proc"] = None

        if job["cancel"]:
            return
        if proc.returncode == 0:
            err_file.unlink(missing_ok=True)
            return
        last_err = err_file.read_text(encoding="utf-8", errors="replace").strip()[-300:]
        print(f"[vidscribe] {vcodec} 短片匯出失敗,換下一個編碼器:{last_err}")
    err_file.unlink(missing_ok=True)
    raise RuntimeError(f"ffmpeg 匯出失敗:{last_err}")


def _run(pid: str, media_name: str, job: dict) -> None:
    d = storage.project_dir(pid)
    try:
        iw, ih = burn._probe_size(d / media_name)
        clips.clips_dir(pid).mkdir(exist_ok=True)
        while True:
            with _lock:
                if job["cancel"] or not job["queue"]:
                    break
                cid = job["queue"].pop(0)
                job["current"] = cid
                job["progress"] = 0.0
            # 每支重讀,拿最新的邊界/pan;中途被刪掉就跳過
            clip = next((c for c in clips.load_clips(pid) if c["id"] == cid), None)
            if clip is None:
                continue
            _render_clip(pid, d, media_name, clip, iw, ih, job)
            if job["cancel"]:
                break
            with _lock:
                job["done_ids"].append(cid)
        if job["cancel"]:
            job["status"] = "canceled"
            # 半成品作廢
            cur = job.get("current")
            if cur:
                (clips.clips_dir(pid) / f"{cur}.mp4").unlink(missing_ok=True)
        else:
            job["status"] = "done"
            job["progress"] = 1.0
    except Exception as e:
        traceback.print_exc()
        if job.get("status") != "canceled":
            job["status"] = "error"
            cur = job.get("current")
            job["error"] = f"{cur}:{str(e)[:300]}" if cur else str(e)[:400]
            if cur:
                (clips.clips_dir(pid) / f"{cur}.mp4").unlink(missing_ok=True)
    finally:
        job["proc"] = None
        job["current"] = None
        (d / ASS_NAME).unlink(missing_ok=True)
