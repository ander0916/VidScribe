"""清單式詞庫:「錯誤寫法 → 正確寫法」的純規則取代。

全域共用(跨專案),存在 projects/_dictionary.json,跟著資料夾備份走。
每次辨識完成後自動套用;前端也可以手動套用到目前字幕(走復原系統)。
"""

import json
import os
import threading
import uuid

from . import config

_lock = threading.Lock()


def _file():
    return config.PROJECTS_DIR / "_dictionary.json"


def load() -> list[dict]:
    try:
        with _file().open("r", encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries", [])
        return [e for e in entries if e.get("wrong") and e.get("right")]
    except (OSError, json.JSONDecodeError):
        return []


def _save(entries: list[dict]) -> None:
    path = _file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def add(wrong: str, right: str) -> list[dict]:
    wrong = wrong.strip()
    right = right.strip()
    if not wrong or not right:
        raise ValueError("兩個欄位都要填")
    if wrong == right:
        raise ValueError("兩個寫法一樣,不需要加入")
    with _lock:
        # 同一個錯誤寫法只留最新的一筆
        entries = [e for e in load() if e["wrong"] != wrong]
        entries.append({"id": uuid.uuid4().hex[:8], "wrong": wrong, "right": right})
        _save(entries)
        return entries


def remove(entry_id: str) -> list[dict]:
    with _lock:
        entries = [e for e in load() if e["id"] != entry_id]
        _save(entries)
        return entries


def apply_text(text: str, entries: list[dict]) -> str:
    # 長的先取代,避免短詞吃掉長詞的一部分
    for e in sorted(entries, key=lambda x: len(x["wrong"]), reverse=True):
        text = text.replace(e["wrong"], e["right"])
    return text
