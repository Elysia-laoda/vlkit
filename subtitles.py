"""字幕时间轴：把逐帧的「读出来的一句话」合并成带起止时间的字幕段。

识别类输入都要允许"读错"，所以这里只做**保守合并**：
  - 归一化后完全相同 -> 同一段；
  - 一方为空 -> 视为同一段的延续（字幕可能闪断一帧）；
  - 其余 -> 开新段。
冲突不猜：不同模型的两次读法都留在记录里，交给上层做交叉核对。

clean() 要吃掉模型的几种"包装"：JSON 对象、代码块、引号、以及「无 / No text detected」这类答复。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

_EMPTY_WORDS = {"无", "沒有", "没有", "none", "null", "(无)", "（无）", "无字幕", "空", "n/a", "na", "-", "—"}
_NO_TEXT_HINT = re.compile(r"(no text|not detected|contains no|nothing|无法识别|未检测|没有文字|无文字|纯黑)", re.I)
_PUNCT = re.compile(r"[\s，。、！？；：「」『』（）()\[\]【】…·.,!?;:'\"~]+")
_TEXT_KEYS = ("text", "subtitle", "caption", "content", "result", "ocr", "line", "value", "transcription")


def _dig(obj) -> str | None:
    """从模型返回的 JSON 结构里挖出真正的文本；挖不到返回 None（= 无文字）。"""
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        parts = [p for p in (_dig(x) for x in obj) if p]
        return " ".join(parts) if parts else None
    if isinstance(obj, dict):
        if "error" in obj and len(obj) == 1:
            return None
        for k in _TEXT_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v
        for v in obj.values():          # 退一步：随便哪个字符串字段
            if isinstance(v, str) and v.strip() and not _NO_TEXT_HINT.search(v):
                return v
        return None
    return None


def clean(text) -> str:
    if text is None:
        return ""
    t = str(text).strip()
    if not t:
        return ""
    t = t.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    if t.startswith("{") or t.startswith("["):
        try:
            t = _dig(json.loads(t)) or ""
        except Exception:
            pass
    t = t.strip().strip('"').strip("「」").strip()
    if _NO_TEXT_HINT.search(t):
        return ""
    if t.lower() in _EMPTY_WORDS:
        return ""
    return t.strip()


def canon(text: str) -> str:
    """用于比较的归一化形态：去空白与标点。"""
    return _PUNCT.sub("", text or "")


@dataclass
class SubtitleSegment:
    index: int
    start: float
    end: float
    text: str
    readings: list = field(default_factory=list)   # [(model, text)] 全部原始读法
    frames: list = field(default_factory=list)     # 采样点时间

    def to_dict(self) -> dict:
        return {"index": self.index, "start": self.start, "end": self.end,
                "text": self.text, "readings": self.readings, "samples": self.frames}


def merge_segments(samples: list, *, max_blank: int = 2) -> list:
    """samples: [{'t': float, 'text': str, 'model': str}]（按 t 升序）-> SubtitleSegment 列表。

    max_blank：允许连续多少个"空读数"仍然算同一段（字幕可能闪断一帧）。
    **必须设上限**——否则一处读空会把段落一路拖到下一个变化点（踩过：27s 的术式名一路拖到 36s）。
    """
    segs: list = []
    cur: SubtitleSegment | None = None
    blanks = 0
    for s in samples:
        t = float(s["t"])
        txt = clean(s.get("text"))
        key = canon(txt)
        if cur is None:
            cur = SubtitleSegment(index=0, start=t, end=t, text=txt)
            cur.readings.append((s.get("model", ""), s.get("text", "")))
            cur.frames.append(t)
            continue
        if not key:
            if canon(cur.text) and blanks < max_blank:
                blanks += 1
                cur.end = t
                cur.frames.append(t)
                continue
            # 空档超限：收段，当前样品丢弃（等下一个有字的样品重新开段）
            if canon(cur.text):
                cur.end = min(cur.end, t - 1e-6)
                segs.append(cur)
            cur = None
            continue
        same = (not canon(cur.text)) or key == canon(cur.text)
        if same:
            blanks = 0
            cur.end = t
            cur.frames.append(t)
            cur.readings.append((s.get("model", ""), s.get("text", "")))
            if len(txt) > len(cur.text):
                cur.text = txt
        else:
            cur.end = min(cur.end, t - 1e-6)
            segs.append(cur)
            cur = SubtitleSegment(index=0, start=t, end=t, text=txt)
            cur.readings.append((s.get("model", ""), s.get("text", "")))
            cur.frames.append(t)
            blanks = 0
    if cur is not None:
        segs.append(cur)
    segs = [s for s in segs if canon(s.text)]
    for i, s in enumerate(segs):
        s.index = i
    return segs
