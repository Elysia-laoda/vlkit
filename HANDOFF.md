# HANDOFF —— vlkit 识图 / 听音工具包

> 给接手维护的人（或下一轮的我）。只写"接着干必须知道的"。
> 第一次用请先读 `README.md`；这里是**状态、边界与复验方法**。

---

## 一、一句话现状

**可用、已验证、在服役中。** 本机的「看图 / 读字 / 听音」由它和本地 Vision Router 两条路承担，
技能 `aliyun-vl` 是操作入口。

## 二、装在哪

| 项 | 位置 |
|---|---|
| 工具包 | `C:\Users\27096\.dsh\tools\vlkit\` |
| 操作入口（技能） | `C:\Users\27096\.dsh\skills\aliyun-vl\SKILL.md` |
| 缓存 | `<工具包>\.cache\`，可整个删 |
| 凭据 | `D:\BaiduNetdiskDownload\默认业务空间-apiKey-7666918.csv`（kv 两列：`apiKey` / `openAiCompatible`）；或环境变量 `ALIYUN_DS_KEY` + `ALIYUN_DS_BASE_URL`。**从不打印、从不落盘。** |
| Python | `C:\Users\27096\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`（自带 Pillow；纯标准库即可跑，Pillow 只用于缩放） |
| 人声分离 | 用户自己的 Python 3.14 装了 `demucs 4.1.0` + `torchaudio 2.11`（**不在**上面那个 bundled python 里） |

## 三、已验证到什么程度

| 能力 | 状态 | 证据 |
|---|---|---|
| 凭据 / 端点 / 视觉真调用 | ✅ | `cli.py probe` 现画一张带随机串的图让模型读，读对才报通过 |
| 单图问答 | ✅ | 在带烧录字幕的动画帧上读对了水印与字幕原文 |
| 批量并发 | ✅ | 通配一次 15 张、2.3 秒 |
| 小字 / 字幕 OCR | ✅ | 与另两个模型交叉投票，18 条字幕定稿 |
| 结构化 JSON 输出 | ✅ | 逐帧识图 45 张全部解析成功 |
| 语音转写（日文） | ✅ 但**不可全信** | 分离人声后「無量空処」读对；BGM 段落仍有幻觉 |
| 人在回路的整条管线 | ✅ | 视频 → 逐镜头 → 字幕轴 → 说话人 → 逐图笔记 docx，见 `D:\dshproject\shibuya-02s\HANDOFF.md` |
| 图像缩放 | ✅ | Pillow 通路，`max_side=1280` 默认 |

**没说已验证的**：多语言混合音频、非中文界面截图的大批量、带坐标的 OCR（`qwen-vl-ocr-latest` 那条路没实战用过）。

## 四、怎么复验（照抄即可）

```powershell
$PY  = "C:\Users\27096\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$CLI = "C:\Users\27096\.dsh\tools\vlkit\cli.py"

& $PY $CLI probe                     # 1) 链路自检（必须全绿）
& $PY $CLI models                    # 2) 模型清单
& $PY $CLI ask <任意一张已知内容的图> --q "逐字读出图中文字"   # 3) 端到端
```

**第 1 条不过，后面都不用看**：先查 CSV 是否还在原位、网络是否通（Clash 关掉时国内站也通，但百炼需要外网）。

## 五、边界与脆弱点（按重要性）

1. **强模型会幻读**——任何"让模型逐帧读字"的任务，**必须先做像素门控**，否则约三分之一的段落是假的。
   详见 `LESSONS.md` 第 1 条。
2. **逐字任务不能单模型定案**——多读者 + 中位串投票；本机 Vision Router 是独立第三方。
3. **凭据文件是外部路径**：`D:\BaiduNetdiskDownload\` 那个 CSV 一旦被移动或删除，整条链路会直接失败
   （报"凭据文件不存在"）。要长期稳定，可把值挪进环境变量。
4. **ASR 是生成式的**：同一段音频的措辞会漂（实测整段一致、切片会变）。**当证据用，不当基准用**。
5. **端点绑的是"默认业务空间"**：换工作空间就要换 CSV，模型可用性也可能不同（本 CSV 里列了 394 个模型）。
6. **视觉工具的相对路径按会话工作区解析**——一律传绝对路径。
7. 本机 `browser_*` 工具链不可用（bsk CLI 未装），与识图无关，但别指望用它做网页截图。

## 六、未完成 / 可以继续做

| # | 事项 | 说明 |
|---|---|---|
| 1 | 把 9 个 provider 之外的**记忆空间**与识图打通 | 目前识图的产物落在 Mnemon Document，没有走 Memory Space |
| 2 | **说话人归属**做成可复用步骤 | 现在是项目内的 `run_speaker.py`，值得抽成 `vlkit` 的一等公民 |
| 3 | 带坐标 OCR | `qwen-vl-ocr-latest` 返回框坐标，可用来做"点哪一行"的自动化，未实战 |
| 4 | 视频抽帧的**去重判据** | 现在用时间差（≤0.4s 丢一帧），可以用像素相似度更准 |
| 5 | 与解题器（wxhomework）对接 | ZCode 那条线的硬约束是"无图像输入 → 只能 OCR"；vlkit 可以**直接替代**它，未对接 |

## 七、相关文件（一条链）

- 操作纪律：技能 `aliyun-vl`（`~/.dsh/skills/aliyun-vl/SKILL.md`）
- 本包：`README.md` / `LESSONS.md` / 本文
- 实战工程：`D:\dshproject\shibuya-02s\` —— `HANDOFF.md`（数据流与重跑）、
  `docs\校勘记录.md`（证据链）、`docs\涉谷事变…docx`（成品）
- 长期记录：Mnemon Document `0f4d3b9a`
- 来源：百炼模型清单 `D:\BaiduNetdiskDownload\模型列表.docx`；
  官方 key 文档 https://docs.bailian.console.aliyun.com/zh/model-studio/get-api-key

## 八、变更记录

| 日期 | 变更 |
|---|---|
| 2026-10（建） | 从 `shibuya-02s` 提升为独立工具包；加 `cli.py`（probe/ask/ocr/asr/models） |
| 2026-10 | 逐帧提示词加「不得推断术式名/招式名」硬约束（7 帧误判的根因修复） |
| 2026-10 | 补 `README.md` / `LESSONS.md` / 本文；技能补「默认参数」与「稳健性」两节 |
| 2026-10-30 | 识图默认路线切到 vlkit（用户拍板：Vision Router 的 OVH 链限流 2 次/分钟、并发小，尽量别用）。`cli.py` 修 Windows GBK 控制台下 `UnicodeEncodeError`（模型返回 emoji 即崩），改为强制 UTF-8 输出。技能 `aliyun-vl` 第一节/第五节/第十节已按新路线改写。 |
