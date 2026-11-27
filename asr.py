"""百炼语音识别：走 OpenAI 兼容口的 input_audio。

先整段试；遇到"太长/太大"类 400 再自动切片重试（切片用标准库 wave，不调外部进程）。
"""

from __future__ import annotations

import base64
import io
import pathlib
import wave
from dataclasses import dataclass, field

from .client import VisionClient


@dataclass
class AsrSegment:
    index: int
    start: float
    end: float
    text: str = ""
    ok: bool = False
    error: str = ""
    model: str = ""
    usage: dict = field(default_factory=dict)


def wav_info(path) -> tuple:
    with wave.open(str(path), "rb") as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()


def wav_slice_bytes(path, start_sec: float, end_sec: float) -> bytes:
    """按时间切一段 WAV，返回完整的 WAV 字节（含头）。"""
    with wave.open(str(path), "rb") as w:
        ch, sw, fr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        w.setpos(int(start_sec * fr))
        n = int((end_sec - start_sec) * fr)
        data = w.readframes(n)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as o:
        o.setnchannels(ch)
        o.setsampwidth(sw)
        o.setframerate(fr)
        o.writeframes(data)
    return buf.getvalue()


def _call_asr(client: VisionClient, wav_bytes: bytes, *, model: str, language: str | None) -> tuple:
    data_url = "data:audio/wav;base64," + base64.b64encode(wav_bytes).decode("ascii")
    messages = [{"role": "user", "content": [
        {"type": "input_audio", "input_audio": {"data": data_url, "format": "wav"}},
    ]}]
    extra = {}
    if language:
        extra["asr_options"] = {"language": language}
    r = client.chat(messages, model=model, json_mode=False, max_tokens=4096, extra=extra)
    return r.ok, (r.content or "").strip(), r.error, r.model, r.usage


def transcribe_wav(client: VisionClient, wav_path, *, model: str = "qwen3-asr-flash",
                   language: str | None = "ja", chunk_seconds: float = 25.0) -> list:
    """返回 AsrSegment 列表。整段失败会自动按 chunk_seconds 切片。"""
    path = pathlib.Path(wav_path)
    ch, sw, fr, nf = wav_info(path)
    dur = nf / float(fr)

    ok, text, err, used, usage = _call_asr(client, path.read_bytes(), model=model, language=language)
    if ok and text:
        return [AsrSegment(index=0, start=0.0, end=round(dur, 2), text=text, ok=True,
                           model=used, usage=usage)]

    first_err = err
    segs: list = []
    n = max(1, int(dur // chunk_seconds) + (1 if dur % chunk_seconds else 0))
    for i in range(n):
        s = i * chunk_seconds
        e = min(dur, s + chunk_seconds)
        ok2, text2, err2, used2, usage2 = _call_asr(
            client, wav_slice_bytes(path, s, e), model=model, language=language)
        segs.append(AsrSegment(index=i, start=round(s, 2), end=round(e, 2), text=text2,
                               ok=ok2 and bool(text2), error="" if ok2 else (err2 or first_err),
                               model=used2, usage=usage2))
    return segs
