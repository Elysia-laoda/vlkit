"""内容寻址的落盘缓存：同样的（图 + 提示词 + 模型 + 参数）只花一次钱。"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import tempfile
from typing import Any


def canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


class DiskCache:
    """一层目录、一个 key 一个 .json 文件。原子写（tmp + replace），并发安全。"""

    def __init__(self, root: str | os.PathLike, enabled: bool = True):
        self.root = pathlib.Path(root)
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        if self.enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    def key(self, namespace: str, payload: Any) -> str:
        return f"{namespace}-{digest(payload)}"

    def _path(self, key: str) -> pathlib.Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        p = self._path(key)
        if not p.exists():
            self.misses += 1
            return None
        try:
            self.hits += 1
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            self.misses += 1
            return None

    def put(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "enabled": self.enabled,
                "root": str(self.root)}
