"""凭据与端点配置。

凭据来源优先级：环境变量 ALIYUN_DS_KEY / ALIYUN_DS_BASE_URL > CSV 文件。
任何情况下都不把密钥写进日志或产物。
"""

from __future__ import annotations

import csv
import json
import os
import pathlib
from dataclasses import dataclass

DEFAULT_KEY_CSV = str(pathlib.Path.home() / ".dsh" / "aliyun-ds.csv")
# 本机私有覆盖（不进仓库）：{"csv": "<本机 apiKey CSV 的绝对路径>"}
LOCAL_OVERRIDE = pathlib.Path(__file__).resolve().parent / "vlkit.local.json"


@dataclass(frozen=True)
class Credentials:
    api_key: str
    base_url: str
    host: str = ""
    workspace: str = ""
    source: str = ""

    def masked(self) -> str:
        k = self.api_key or ""
        return f"{k[:6]}...{k[-4:]}(len={len(k)})" if len(k) > 12 else "(short)"

    def __repr__(self) -> str:  # 防止 dataclass 默认 __repr__ 打印密钥
        return f"Credentials(base_url={self.base_url!r}, key={self.masked()}, source={self.source!r})"

    __str__ = __repr__


def _read_csv(path: pathlib.Path) -> dict:
    kv: dict = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0].strip():
                kv[row[0].strip()] = row[1].strip()
    return kv


def load_credentials(csv_path: str | None = None) -> Credentials:
    """读凭据。默认读本机百炼「默认业务空间」的 apiKey CSV。"""
    env_key = os.environ.get("ALIYUN_DS_KEY")
    env_base = os.environ.get("ALIYUN_DS_BASE_URL")
    if env_key and env_base:
        return Credentials(api_key=env_key, base_url=env_base.rstrip("/"), source="env")

    override = None
    if LOCAL_OVERRIDE.exists():
        try:
            override = json.loads(LOCAL_OVERRIDE.read_text(encoding="utf-8")).get("csv")
        except Exception:  # 本地覆盖写坏就当没有
            override = None
    p = pathlib.Path(csv_path or os.environ.get("ALIYUN_KEY_CSV") or override or DEFAULT_KEY_CSV)
    if not p.exists():
        raise FileNotFoundError(f"凭据文件不存在：{p}；可设 ALIYUN_KEY_CSV 或 ALIYUN_DS_KEY/ALIYUN_DS_BASE_URL")
    kv = _read_csv(p)
    key = kv.get("apiKey", "")
    base = (kv.get("openAiCompatible") or "").rstrip("/")
    if not key or not base:
        raise RuntimeError(f"凭据文件 {p.name} 缺少 apiKey 或 openAiCompatible 字段")
    return Credentials(api_key=key, base_url=base, host=kv.get("apiHost", ""),
                       workspace=kv.get("workspaceId", ""), source=str(p))
