"""字幕带的像素门控：先用像素判定"这一格到底有没有字幕"，再决定要不要花 OCR 的钱。

判据（实测有效）：字幕是**亮字形 + 黑描边**。取 min(R,G,B)>225 的亮像素，与 2 像素膨胀后的
暗像素（max(R,G,B)<70）求交 —— 动画里的白头发/白衣服没有描边，不会命中。
再只看下半幅，字幕通常落在那里。

实测本片：无字幕帧 glyph_low 中位数 86，有字幕帧 p90 为 2618，双峰分得很开。
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import numpy as np
from PIL import Image

DEFAULT_THRESHOLD = 600


def glyph_metric(path) -> int:
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    h = a.shape[0]
    mn = a.min(axis=2)
    bright = mn > 225
    dark = a.max(axis=2) < 70
    d = dark.copy()
    for _ in range(2):
        d = d | np.roll(d, 1, 0) | np.roll(d, -1, 0) | np.roll(d, 1, 1) | np.roll(d, -1, 1)
    glyph = bright & d
    return int(glyph[h // 2:, :].sum())


def scan(files: list, *, fps: float = 2.0, threshold: int = DEFAULT_THRESHOLD) -> list:
    """返回 [{'i','t','glyph','on'}]。"""
    out = []
    for i, f in enumerate(files):
        g = glyph_metric(f)
        out.append({"i": i, "t": round(i / fps, 3), "glyph": g, "on": g >= threshold})
    return out


@dataclass
class Window:
    index: int
    start: float
    end: float
    samples: list        # 该窗口内的采样序号

    def to_dict(self) -> dict:
        return {"index": self.index, "start": self.start, "end": self.end,
                "samples": self.samples}


def windows_from_scan(rows: list, *, fps: float = 2.0, pad: float = 0.25,
                      max_merge_gap: float = 0.75) -> list:
    """把 on 的采样点连成窗口；间隔不超过 max_merge_gap 的相邻段合并（字幕中间可能闪断）。"""
    raw: list = []
    cur: list = []
    for r in rows:
        if r["on"]:
            cur.append(r)
        elif cur:
            raw.append(cur)
            cur = []
    if cur:
        raw.append(cur)
    merged: list = []
    for seg in raw:
        if merged and seg[0]["t"] - merged[-1][-1]["t"] <= max_merge_gap:
            merged[-1].extend(seg)
        else:
            merged.append(list(seg))
    wins = []
    for i, seg in enumerate(merged):
        wins.append(Window(index=i, start=max(0.0, seg[0]["t"] - pad),
                           end=seg[-1]["t"] + pad,
                           samples=[r["i"] for r in seg]))
    return wins
