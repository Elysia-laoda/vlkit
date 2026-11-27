# vlkit —— 本机识图 / 听音工具包

**一句话**：把「看图、读字、听音」变成一条命令，或者三行 Python。

> 面向第一次拿到这个包的人（或 agent）：**这是什么、怎么跑、目录里有什么**。
> 操作纪律（分流规则、默认参数、硬规矩）在技能 `aliyun-vl` 里；
> 踩过的坑与证据在 `LESSONS.md`；当前状态与复验方法在 `HANDOFF.md`。

---

## 1. 它解决什么问题

本机的对话模型历史上**没有图像输入**——「屏幕侧只能走 OCR」曾经是一条硬约束。
vlkit 走阿里云百炼（DashScope）的 **OpenAI 兼容口**，把视觉 / OCR / 语音三条能力补齐。
纯标准库（图片缩放用可选的 Pillow），**没有构建、没有常驻进程、没有 npm 依赖**。

## 2. 两条路，先分流再动手

本机现在有两条独立的看图路径，**别混用、也别重复造**：

| | 本地 Vision Router | vlkit（百炼） |
|---|---|---|
| 入口 | `vision_describe` / `vision_ocr` / `vision_ground` / `vision_crop` / `vision_colors` / `vision_pixel_diff` / `vision_html_screenshot` | `python cli.py ask|ocr|asr`，或 `import vlkit` |
| 密钥 | 不需要 | 自动从 CSV 读（**不用问用户**） |
| 强在 | 随手看一眼、定位、裁剪、取色、像素比对、渲染 HTML 截图 | **批量**、**强制 JSON**、**小字 OCR**、**语音转写**、**独立第三方复核** |
| 弱在 | 不适合几十张批量；**几何描述与"有没有某物"的判断会出错** | 强模型**会幻读**（见 LESSONS 第 1 条） |

**默认动作**：随手看 → 本地 Router；要逐字、要批量、要结构化、要听音频 → 走 vlkit。

## 3. 三行上手

```python
import sys; sys.path.insert(0, r"C:\Users\27096\.dsh\tools")
from vlkit import VisionClient, load_credentials

cli = VisionClient(load_credentials(), model="qwen3-vl-flash",
                   cache_dir=r"C:\Users\27096\.dsh\tools\vlkit\.cache")
print(cli.analyze_image(r"图.png", "逐字读出图中所有文字，没有就回「无」", json_mode=False).content)
```

批量并发用 `cli.analyze_images(paths, prompt, keys=[...])`；
一次调用送多张（胶片条式提问）用 `cli.analyze_groups([[p1,p2,p3], ...], prompt, prompt_fn=...)`。

## 4. 命令行

```powershell
$PY  = "C:\Users\27096\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$CLI = "C:\Users\27096\.dsh\tools\vlkit\cli.py"

& $PY $CLI probe                        # 自检：凭据 + 端点 + 一次真视觉调用（先跑这个）
& $PY $CLI ask 图.png "这张图里有什么"
& $PY $CLI ask "out/frames/*.jpg" --q "谁在说话" --json    # 通配/目录批量 + 强制 JSON
& $PY $CLI ocr 图.png                   # 只读文字（自动切到 qwen3.5-ocr）
& $PY $CLI asr 音频.wav --lang ja        # 语音转写
& $PY $CLI models                       # 列推荐模型
```

`probe` 是这条路唯一的权威自检：它**现场画一张带随机串的图**发给视觉模型，读得出来才报通过。
新会话第一次要用识图前跑一次，通了就不要再怀疑环境。

## 5. 模型怎么挑（2026 实测可用）

| 用途 | 首选 | 备选 |
|---|---|---|
| 逐帧 / 单图结构化描述 | `qwen3-vl-flash` | `qwen3-vl-plus`（更准，复核用） |
| 小字 / 字幕 OCR | `qwen3.5-ocr` | `qwen-vl-ocr-latest`（带坐标）、`qwen3-vl-plus` |
| 强文本推理 / 成句 / 裁决 | `qwen3.7-plus` | `deepseek-v4-pro`、`qwen3-max` |
| 语音转写 | `qwen3-asr-flash`（`--lang ja`） | `qwen3.5-omni-plus` |
| 人声分离（本地 CPU） | demucs `htdemucs` | — |

## 6. 目录里有什么

| 文件 | 用途 |
|---|---|
| `README.md` | 本文（介绍） |
| `LESSONS.md` | **识图经验**：按代价排序的坑与证据 |
| `HANDOFF.md` | **交接文档**：状态、边界、复验方法、未完成 |
| `cli.py` | 命令行入口：probe / ask / ocr / asr / models |
| `vlkit/` | 模块本体：client（并发/缓存/重试/结构化）、config（凭据）、bands（像素门控）、frames（镜头切分）、subtitles（字幕合并）、asr、schema、prompts |
| `.cache/` | 内容寻址缓存（图字节 + 提示词 + 模型）。可随时整个删掉，只会让下次变慢 |

模块本身是**无状态、可整体复制**的：拷到任何地方，加一行 `sys.path.insert` 就能用。
