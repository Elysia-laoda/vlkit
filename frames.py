r"""镜头切分与关键帧抽取（依赖本机 ffmpeg / ffprobe）。

ffmpeg 滤镜参数里 ':' 是分隔符，Windows 的 "D:\..." 会被切断 —— 所以元数据文件一律写成
相对文件名，并让 ffmpeg 在临时目录里跑（踩过：绝对路径导致 scene 检测静默返回 0 个切点）。
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import tempfile
from dataclasses import dataclass, field

_PTS = re.compile(r"pts_time:([0-9.]+)")
_SCORE = re.compile(r"lavfi\.scene_score=([0-9.]+)")


@dataclass
class Shot:
    index: int
    start: float
    end: float
    frames: list = field(default_factory=list)   # 要抽帧的时间点（秒）
    files: list = field(default_factory=list)    # 抽出来的图片路径

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def probe_duration(video: str, ffprobe: str = "ffprobe") -> float:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", video],
        capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def detect_shots(video: str, *, threshold: float = 0.2, ffmpeg: str = "ffmpeg",
                 duration: float | None = None) -> list:
    """返回切点时间戳列表（不含 0 与片尾）。"""
    with tempfile.TemporaryDirectory() as td:
        args = [ffmpeg, "-v", "error", "-y", "-i", str(pathlib.Path(video).resolve()),
                "-vf", f"select='gt(scene,{threshold})',metadata=print:file=scene.txt",
                "-an", "-f", "null", "NUL"]
        subprocess.run(args, cwd=td, capture_output=True, text=True)
        p = pathlib.Path(td) / "scene.txt"
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    cuts = []
    for i, ln in enumerate(lines):
        m = _PTS.search(ln)
        if m:
            cuts.append(round(float(m.group(1)), 3))
    return cuts


def shots_from_cuts(cuts, duration: float) -> list:
    """切点 -> (start, end) 段。"""
    bounds = [0.0] + [c for c in cuts if 0 < c < duration] + [duration]
    out = []
    for i in range(len(bounds) - 1):
        out.append(Shot(index=i, start=round(bounds[i], 3), end=round(bounds[i + 1], 3)))
    return out


def build_shots(cuts, duration: float, *, min_shot: float = 0.4, max_gap: float = 5.0) -> list:
    """合并过短镜头（闪光切），并给过长镜头补帧，避免一个大镜头只有一张图。

    min_shot: 相邻切点间隔小于它则视为同一次动作闪光，合并掉。
    max_gap : 单个镜头超过它就在内部按 max_gap 均分多抽几张。
    """
    kept: list = []
    last = 0.0
    for c in sorted(c for c in cuts if 0 < c < duration):
        if c - last >= min_shot:
            kept.append(c)
            last = c
    shots = shots_from_cuts(kept, duration)
    for s in shots:
        d = s.duration
        if d <= max_gap:
            s.frames = [round(s.start + d / 2, 3)]
        else:
            n = int(d // max_gap) + 1
            step = d / n
            s.frames = [round(s.start + step * (k + 0.5), 3) for k in range(n)]
    for i, s in enumerate(shots):
        s.index = i
    return shots


def extract_frames(video: str, shots, outdir: str, *, prefix: str = "s",
                   ffmpeg: str = "ffmpeg", quality: int = 3, width: int | None = None) -> list:
    """按 shot.frames 抽帧，写 <prefix>{shot:02d}-{k}.jpg，回填 shot.files。"""
    out = pathlib.Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    vf = f"scale={width}:-2" if width else None
    produced = []
    for s in shots:
        s.files = []
        for k, t in enumerate(s.frames):
            name = f"{prefix}{s.index:02d}-{k}.jpg"
            dst = out / name
            args = [ffmpeg, "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(pathlib.Path(video).resolve()),
                    "-frames:v", "1", "-q:v", str(quality)]
            if vf:
                args += ["-vf", vf]
            args.append(str(dst))
            subprocess.run(args, capture_output=True, text=True)
            if dst.exists() and dst.stat().st_size > 0:
                s.files.append(str(dst))
                produced.append(str(dst))
    return produced
