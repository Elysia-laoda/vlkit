"""vlkit —— 阿里云百炼（DashScope）视觉 / 语音调用的可复用模块。

设计目标（对齐"完整模块"要求）：
  * 批量   : analyze_many() 一次跑几十张图，不手写循环；
  * 并发   : 线程池，max_workers 可配；
  * 缓存   : 内容寻址落盘（图字节 + 提示词 + 参数 → sha256），命中即零成本返回；
  * 重试   : 429/5xx/网络错误 指数退避 + 抖动，逐个错误分类；
  * 结构化 : 强制 JSON 输出 + 本地解析/修复，附带 usage 记账。

凭据只从 CSV / 环境变量读，不落盘、不打印。
"""

from .config import Credentials, load_credentials
from .cache import DiskCache
from .client import ChatResult, VisionClient
from .frames import Shot, build_shots, detect_shots, extract_frames
from .asr import AsrSegment, transcribe_wav

__all__ = [
    "Credentials", "load_credentials",
    "DiskCache",
    "ChatResult", "VisionClient",
    "Shot", "build_shots", "detect_shots", "extract_frames",
    "AsrSegment", "transcribe_wav",
]
__version__ = "1.0.0"
