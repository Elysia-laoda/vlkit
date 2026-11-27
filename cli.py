#!/usr/bin/env python
r"""vlkit CLI —— 一条命令完成 识图 / 读字 / 听音 / 自检。

  python cli.py probe                      # 自检：凭据 + 端点 + 视觉一次真调用（先跑这个）
  python cli.py ask 图.png "这张图里有什么"
  python cli.py ask "out/frames/*.jpg" --q "画面里谁在说话" --json
  python cli.py ocr 图.png                 # 只读文字（小字/字幕用 qwen3.5-ocr）
  python cli.py asr 音频.wav --lang ja     # 语音转写

凭据从 CSV 或环境变量读，永不打印。
"""

from __future__ import annotations

import argparse
import glob as _glob
import json
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from vlkit import VisionClient, load_credentials  # noqa: E402
from vlkit.asr import transcribe_wav  # noqa: E402

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
DEFAULT_MODEL = "qwen3-vl-flash"
OCR_MODEL = "qwen3.5-ocr"
OK_TOKEN = "DSH-VLKIT-7391"


def expand(patterns) -> list:
    out = []
    for p in patterns:
        q = pathlib.Path(p)
        if q.is_dir():
            out += [str(x) for x in sorted(q.iterdir()) if x.suffix.lower() in IMG_EXT]
        elif any(c in p for c in "*?["):
            out += sorted(x for x in _glob.glob(p) if pathlib.Path(x).suffix.lower() in IMG_EXT)
        else:
            out.append(p)
    return out


def make_client(a) -> VisionClient:
    return VisionClient(load_credentials(), model=a.model,
                        cache_dir=a.cache, max_workers=a.workers, verbose=not a.quiet)


def cmd_probe(a) -> int:
    creds = load_credentials()
    print(f"[1/3] 凭据: {creds.masked()}  端点: {creds.base_url}  来源: {creds.source}")
    cli = make_client(a)
    r = cli.chat([{"role": "user", "content": "只回答两个字：正常"}], model=a.model, max_tokens=16)
    if not r.ok:
        print(f"[2/3] 文本调用 失败: {r.error}")
        return 1
    print(f"[2/3] 文本调用 通过（{r.model} {r.latency_ms}ms）")

    # 真视觉：现场生成一张带随机串的图，看模型读不读得出来
    with tempfile.TemporaryDirectory() as td:
        img = pathlib.Path(td) / "probe.png"
        try:
            from PIL import Image, ImageDraw
            im = Image.new("RGB", (520, 130), "white")
            ImageDraw.Draw(im).text((16, 44), OK_TOKEN, fill="black")
            im.save(img)
        except Exception as e:
            print(f"[3/3] 视觉调用 跳过（Pillow 不可用: {e}）")
            return 0
        v = cli.analyze_image(str(img),
                              "读出这张图里的那串字母数字，原样输出，不要解释。", json_mode=False)
        got = (v.content or "")
        if v.ok and OK_TOKEN.lower() in got.lower().replace("-", "-"):
            print(f"[3/3] 视觉调用 通过（{v.model} {v.latency_ms}ms，读出 {OK_TOKEN}）")
            return 0
        print(f"[3/3] 视觉调用 可疑：期望读出 {OK_TOKEN}，实际 {got[:60]!r}  err={v.error[:80]}")
        return 1


def cmd_ask(a) -> int:
    imgs = expand(a.images)
    if not imgs:
        print("没有匹配到图片", file=sys.stderr)
        return 2
    prompt = a.q or "详细描述这张图：画面里有什么、有哪些文字（逐字抄出）、主体在做什么。"
    cli = make_client(a)
    t0 = time.time()
    if len(imgs) == 1:
        rs = [cli.analyze_image(imgs[0], prompt, json_mode=a.json, max_tokens=a.max_tokens,
                                max_side=a.max_side, model=a.model)]
    else:
        rs = cli.analyze_images(imgs, prompt, json_mode=a.json, max_tokens=a.max_tokens,
                                max_side=a.max_side, model=a.model,
                                keys=[pathlib.Path(x).name for x in imgs])
    for f, r in zip(imgs, rs):
        print(f"### {pathlib.Path(f).name}" + ("  [cache]" if r.cached else ""))
        print(r.json_obj if (a.json and r.json_obj is not None) else (r.content or f"<失败: {r.error}>"))
    print(f"--- {len(imgs)} 张，{time.time() - t0:.1f}s，cache={cli.cache.hits}/{cli.cache.hits + cli.cache.misses} ---",
          file=sys.stderr)
    return 0


def cmd_ocr(a) -> int:
    imgs = expand(a.images)
    cli = make_client(a)
    m = a.model if a.model != DEFAULT_MODEL else OCR_MODEL
    prompt = "逐字读出图中所有文字，按从上到下、从左到右的顺序输出。没有文字就只输出：无"
    rs = cli.analyze_images(imgs, prompt, model=m, json_mode=False, max_tokens=2000,
                            max_side=a.max_side, keys=[pathlib.Path(x).name for x in imgs])
    for f, r in zip(imgs, rs):
        print(f"### {pathlib.Path(f).name}")
        print((r.content or f"<失败: {r.error}>").strip())
    return 0


def cmd_asr(a) -> int:
    cli = make_client(a)
    segs = transcribe_wav(cli, a.audio, language=a.lang or None, chunk_seconds=a.chunk)
    for s in segs:
        print(f"[{s.start:7.2f}-{s.end:7.2f}] {s.text}" if s.ok else f"[{s.start:7.2f}] <失败 {s.error[:60]}>")
    return 0


def cmd_models(a) -> int:
    print("""推荐模型（百炼默认业务空间，免费额度充足）
  逐帧/单图结构化描述  qwen3-vl-flash（快）      qwen3-vl-plus（更准，适合复核）
  小字/字幕 OCR        qwen3.5-ocr               qwen-vl-ocr-latest（返回坐标）
  强文本推理/定稿      qwen3.7-plus              deepseek-v4-pro、qwen3-max
  语音转写             qwen3-asr-flash（--lang ja）   qwen3.5-omni-plus
  人声分离            本地 demucs（python -m demucs --two-stems=vocals -n htdemucs）""")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="vlkit", description="百炼多模态一条命令")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--cache", default=str(pathlib.Path.home() / ".dsh" / "tools" / "vlkit" / ".cache"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-side", type=int, default=1280)
    ap.add_argument("--max-tokens", type=int, default=1200)
    ap.add_argument("--quiet", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="自检：凭据/端点/视觉真调用").set_defaults(fn=cmd_probe)
    sub.add_parser("models", help="列出推荐模型").set_defaults(fn=cmd_models)

    p = sub.add_parser("ask", help="问图（支持通配符/目录，多图并发）")
    p.add_argument("images", nargs="+")
    p.add_argument("--q", default="", help="要问的问题")
    p.add_argument("--json", action="store_true", help="要求 JSON 输出")
    p.set_defaults(fn=cmd_ask)

    p = sub.add_parser("ocr", help="只读文字")
    p.add_argument("images", nargs="+")
    p.set_defaults(fn=cmd_ocr)

    p = sub.add_parser("asr", help="语音转写")
    p.add_argument("audio")
    p.add_argument("--lang", default="ja")
    p.add_argument("--chunk", type=float, default=25.0)
    p.set_defaults(fn=cmd_asr)

    # Windows 控制台默认 GBK，模型返回的 emoji / 特殊符号会直接抛
    # UnicodeEncodeError 把整个命令打挂（实测 qwen3-vl-plus 返回 ☎ 即触发）。
    # 统一按 UTF-8 输出、坏字符替换，绝不让打印错误吞掉结果。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
