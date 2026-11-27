"""百炼 OpenAI 兼容口的多模态客户端：并发 + 缓存 + 重试 + 结构化输出。

只用标准库（urllib），避免额外依赖；图片缩放交给 Pillow（可选）。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import pathlib
import random
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from .cache import DiskCache
from .config import Credentials

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


@dataclass
class ChatResult:
    ok: bool
    content: str = ""
    json_obj: Any = None
    model: str = ""
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0
    attempts: int = 0
    cached: bool = False
    error: str = ""
    request_id: str = ""
    key: str = ""

    @property
    def json_ok(self) -> bool:
        return self.json_obj is not None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "content": self.content, "json_obj": self.json_obj,
                "model": self.model, "usage": self.usage, "latency_ms": self.latency_ms,
                "attempts": self.attempts, "cached": self.cached, "error": self.error,
                "request_id": self.request_id, "key": self.key}


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_image_bytes(path_or_bytes, max_side: int | None = 1280, quality: int = 88) -> tuple[bytes, str, str]:
    """返回 (JPEG 字节, sha256, data-url)。max_side=None 表示不缩放。"""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        raw = bytes(path_or_bytes)
    else:
        raw = pathlib.Path(path_or_bytes).read_bytes()

    if max_side:
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(raw))
            im = im.convert("RGB")
            if max(im.size) > max_side:
                im.thumbnail((max_side, max_side))
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=quality, optimize=True)
                raw = buf.getvalue()
        except ImportError:
            pass
        except Exception:
            pass  # 缩放失败就用原图

    h = _sha256(raw)
    return raw, h, "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def _signature(messages: Sequence[dict]) -> list:
    """把消息里的 base64 图/音替换成摘要，好让缓存键稳定且不重复哈希大块数据。"""
    sig: list = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            sig.append([m.get("role"), c])
            continue
        parts = []
        for p in c or []:
            t = p.get("type")
            if t == "image_url":
                url = p["image_url"]["url"]
                b64 = url.split(",", 1)[-1]
                parts.append(["image", _sha256(b64.encode("ascii")) if not url.startswith("http") else url])
            elif t == "input_audio":
                b64 = p["input_audio"]["data"].split(",", 1)[-1]
                parts.append(["audio", _sha256(b64.encode("ascii"))])
            else:
                parts.append([t, p.get("text", "")])
        sig.append([m.get("role"), parts])
    return sig


class VisionClient:
    def __init__(self, creds: Credentials, *, model: str = "qwen3-vl-flash",
                 cache_dir: str | None = None, cache_enabled: bool = True,
                 max_workers: int = 6, timeout: int = 180, max_retries: int = 4,
                 verbose: bool = True):
        self.creds = creds
        self.model = model
        self.max_workers = max_workers
        self.timeout = timeout
        self.max_retries = max_retries
        self.verbose = verbose
        self.cache = DiskCache(cache_dir or ".vlcache", enabled=cache_enabled)
        self._lock = threading.Lock()
        self.usage_total: dict = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}

    # ---------- 底层 ----------
    def _post(self, payload: dict) -> tuple[int, dict, str]:
        req = urllib.request.Request(
            f"{self.creds.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.creds.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
                return resp.status, json.loads(body), ""
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(body), ""
            except Exception:
                return e.code, {}, body[:500]
        except Exception as e:  # 网络层
            return 0, {}, f"{type(e).__name__}: {e}"

    def chat(self, messages: Sequence[dict], *, model: str | None = None,
             json_mode: bool = False, max_tokens: int = 1024,
             temperature: float | None = None, use_cache: bool = True,
             extra: dict | None = None, key: str = "") -> ChatResult:
        model = model or self.model
        params: dict[str, Any] = {"model": model, "max_tokens": max_tokens}
        if temperature is not None:
            params["temperature"] = temperature
        if json_mode:
            params["response_format"] = {"type": "json_object"}
        if extra:
            params.update(extra)

        ckey = self.cache.key("chat", {"params": params, "messages": _signature(messages)})
        if use_cache:
            hit = self.cache.get(ckey)
            if hit is not None:
                return ChatResult(**{**hit, "cached": True, "key": key})

        payload = {"messages": list(messages), **params}
        t0 = time.time()
        last_err = ""
        for attempt in range(1, self.max_retries + 1):
            status, data, err = self._post(payload)
            if status == 200 and data.get("choices"):
                msg = data["choices"][0].get("message", {})
                content = msg.get("content") or ""
                if isinstance(content, list):  # 某些版本会给分块
                    content = "".join(x.get("text", "") for x in content if isinstance(x, dict))
                jobj = None
                if json_mode or content.strip().startswith("{"):
                    try:
                        jobj = json.loads(content)
                    except Exception:
                        m = _JSON_BLOCK.search(content)
                        if m:
                            try:
                                jobj = json.loads(m.group(0))
                            except Exception:
                                jobj = None
                res = ChatResult(ok=bool(content.strip()), content=content, json_obj=jobj,
                                 model=data.get("model", model), usage=data.get("usage", {}) or {},
                                 latency_ms=int((time.time() - t0) * 1000), attempts=attempt,
                                 request_id=data.get("id", ""), key=key)
                with self._lock:
                    u = res.usage
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        self.usage_total[k] = self.usage_total.get(k, 0) + int(u.get(k, 0) or 0)
                    self.usage_total["calls"] += 1
                if use_cache and res.ok:
                    self.cache.put(ckey, res.to_dict())
                return res

            # 失败
            api_err = ""
            if isinstance(data, dict):
                api_err = (data.get("error") or {}).get("message", "") if isinstance(data.get("error"), dict) else str(data.get("error", ""))
            last_err = f"HTTP {status} {api_err or err}".strip()
            retryable = status in RETRY_STATUS or status == 0
            if not retryable or attempt == self.max_retries:
                break
            delay = min(30.0, 1.5 * (2 ** (attempt - 1))) * (0.7 + random.random() * 0.6)
            if self.verbose:
                print(f"    [retry {attempt}/{self.max_retries}] {last_err} -> sleep {delay:.1f}s", flush=True)
            time.sleep(delay)

        return ChatResult(ok=False, model=model, error=last_err or "unknown",
                          latency_ms=int((time.time() - t0) * 1000), attempts=self.max_retries, key=key)

    # ---------- 便捷封装 ----------
    @staticmethod
    def text_part(text: str) -> dict:
        return {"type": "text", "text": text}

    @staticmethod
    def image_part(path_or_bytes, max_side: int | None = 1280) -> dict:
        _, _, url = load_image_bytes(path_or_bytes, max_side=max_side)
        return {"type": "image_url", "image_url": {"url": url}}

    def analyze_image(self, image, prompt: str, *, system: str | None = None,
                      model: str | None = None, json_mode: bool = True,
                      max_tokens: int = 1024, max_side: int = 1280, key: str = "") -> ChatResult:
        msgs: list = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": [self.image_part(image, max_side=max_side),
                                                 self.text_part(prompt)]})
        return self.chat(msgs, model=model, json_mode=json_mode, max_tokens=max_tokens, key=key)

    def analyze_images(self, images: Sequence, prompt: str, *, system: str | None = None,
                       model: str | None = None, json_mode: bool = True, max_tokens: int = 1024,
                       max_side: int = 1280, keys: Sequence[str] | None = None,
                       on_done: Callable[[int, ChatResult], None] | None = None,
                       max_workers: int | None = None) -> list[ChatResult]:
        """并发跑一批图。返回顺序与输入一致。"""
        keys = list(keys) if keys else [f"#{i}" for i in range(len(images))]
        results: list[ChatResult | None] = [None] * len(images)

        def work(i: int) -> tuple[int, ChatResult]:
            return i, self.analyze_image(images[i], prompt, system=system, model=model,
                                         json_mode=json_mode, max_tokens=max_tokens,
                                         max_side=max_side, key=keys[i])

        with ThreadPoolExecutor(max_workers=max_workers or self.max_workers) as ex:
            futs = [ex.submit(work, i) for i in range(len(images))]
            done = 0
            for f in as_completed(futs):
                i, r = f.result()
                results[i] = r
                done += 1
                if on_done:
                    on_done(i, r)
                elif self.verbose:
                    tag = "cache" if r.cached else ("ok" if r.ok else "FAIL")
                    print(f"    [{done}/{len(images)}] {keys[i]} {tag} {r.latency_ms}ms {r.error[:80]}", flush=True)
        return [r if r is not None else ChatResult(ok=False, error="missing") for r in results]

    def analyze_groups(self, groups: Sequence[Sequence], prompt, *, system: str | None = None,
                       model: str | None = None, json_mode: bool = True, max_tokens: int = 1024,
                       max_side: int = 1280, keys: Sequence[str] | None = None,
                       prompt_fn: Callable[[int], str] | None = None,
                       on_done: Callable[[int, ChatResult], None] | None = None,
                       max_workers: int | None = None) -> list[ChatResult]:
        """groups: 每一项是"一次调用里一起送的若干张图"（胶片条式提问）。返回顺序与输入一致。"""
        keys = list(keys) if keys else [f"g{i}" for i in range(len(groups))]
        results: list[ChatResult | None] = [None] * len(groups)

        def work(i: int) -> tuple[int, ChatResult]:
            content = [self.image_part(p, max_side=max_side) for p in groups[i]]
            content.append(self.text_part(prompt_fn(i) if prompt_fn else prompt))
            msgs: list = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": content})
            return i, self.chat(msgs, model=model, json_mode=json_mode,
                                max_tokens=max_tokens, key=keys[i])

        with ThreadPoolExecutor(max_workers=max_workers or self.max_workers) as ex:
            futs = [ex.submit(work, i) for i in range(len(groups))]
            done = 0
            for f in as_completed(futs):
                i, r = f.result()
                results[i] = r
                done += 1
                if on_done:
                    on_done(i, r)
                elif self.verbose:
                    tag = "cache" if r.cached else ("ok" if r.ok else "FAIL")
                    print(f"    [{done}/{len(groups)}] {keys[i]} {tag} {r.latency_ms}ms {r.error[:70]}", flush=True)
        return [r if r is not None else ChatResult(ok=False, error="missing") for r in results]

    def stats(self) -> dict:
        return {"cache": self.cache.stats(), "usage_total": dict(self.usage_total)}
