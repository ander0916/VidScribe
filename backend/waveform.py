import json
import wave
from pathlib import Path

import numpy as np

# 每秒峰值取樣數:50 → 每 20ms 一根,30 分鐘影片約 90k 個值(gzip 後很小)
RATE = 50


def generate(wav_path: Path, out_path: Path) -> None:
    with wave.open(str(wav_path), "rb") as w:
        sr = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    chunk = max(sr // RATE, 1)
    usable = len(data) - len(data) % chunk
    if usable <= 0:
        peaks: list[float] = []
    else:
        arr = np.abs(data[:usable].astype(np.int32)).reshape(-1, chunk)
        peaks = (arr.max(axis=1) / 32768.0).round(3).tolist()
    tmp = out_path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"rate": RATE, "peaks": peaks}, f)
    tmp.replace(out_path)
