"""识图任务的结构化 schema 与提示词。

一段一句：帧分析（qwen3-vl） -> 序列定稿（强文本模型）。
"""

from __future__ import annotations

FRAME_SYSTEM = (
    "你是《咒术回战》涉谷事变片段的逐帧校勘员。"
    "你只依据画面本身作答，看不清或判断不了就写「不确定」，绝不凭剧情猜测。"
)

FRAME_PROMPT = """这是同一条动画短片中的一帧。短片背景：涉谷事变，五条悟在地铁站展开 0.2 秒的领域展开「无量空处」。

只输出一个 JSON 对象，字段如下：
{
  "subtitle": "画面里烧录的中文字幕原文；没有字幕就给空字符串。只抄字幕本体，绝不抄左上角水印「枫泉 bilibili」。",
  "speaker": "这句字幕是谁说的。依据画面里谁在张嘴、谁是被拍摄主体、台词内容综合判断；判断不了写「不确定」。只写角色名，例如 五条悟 / 虎杖悠仁 / 咒灵 / 民众 / 旁白。",
  "subtitle_confidence": 0.0,
  "action": "这一帧在演什么，一句话，40 字以内，写成可直接当笔记用的陈述句。",
  "characters": ["画面中可辨认的角色名"],
  "on_screen_text": ["除字幕外画面上出现的其他文字，例如招牌、术式名、UI 文字；没有就给空数组"],
  "scene": "场景地点，例如 地铁站台 / 车厢内 / 街道 / 天空；判断不了写「不确定」",
  "is_transition": false
}

硬性要求：
- subtitle 必须是画面上真实存在的字，逐字照抄（含标点）；没有就是 ""。不要凭剧情补台词。
- 画面若是纯黑、纯色或转场闪光，subtitle 给 ""，is_transition 给 true，action 写「转场：<描述>」。
- action 里不要出现「图片」「这一帧」这类词，直接叙述发生的事。
- **不要替画面推断术式名或招式名**。只有画面里明确出现结印手势、成形的黑色/球形结界、或异空间背景时，
  才允许写「展开领域」这类判断；仅仅是发光、彩色特效、残影、跳跃或挥拳，一律按动作本身描述
  （实测：把普通战斗特效写成「展开领域」会让后续成句整段错位）。
"""

_KEYS = ["subtitle", "speaker", "subtitle_confidence", "action", "characters",
         "on_screen_text", "scene", "is_transition"]


def normalize_frame(obj) -> dict:
    """把模型输出收敛成固定字段，缺的补默认值。"""
    out = {"subtitle": "", "speaker": "", "subtitle_confidence": 0.0, "action": "",
           "characters": [], "on_screen_text": [], "scene": "", "is_transition": False}
    if not isinstance(obj, dict):
        return out
    for k in _KEYS:
        if k not in obj:
            continue
        v = obj[k]
        if k in ("characters", "on_screen_text"):
            out[k] = [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])
        elif k == "subtitle_confidence":
            try:
                out[k] = max(0.0, min(1.0, float(v)))
            except (TypeError, ValueError):
                out[k] = 0.0
        elif k == "is_transition":
            out[k] = bool(v)
        else:
            out[k] = str(v or "").strip()
    if out["subtitle"] and out["subtitle"] in ("枫泉 bilibili", "枫泉bilibili"):
        out["subtitle"] = ""
    return out


SPEAKER_SYSTEM = (
    "你是动画分镜的配音归属分析员。给你若干张按时间排列的连续画面，你要判断某句字幕是谁说的。"
    "先看口型与发声迹象，再看摄影机主体，最后才参考剧情常识；证据不足时必须写「不确定」，不要猜。"
)

SEQUENCE_SYSTEM = (
    "你在为一条动画短片写逐图笔记，体例模仿《超详细复盘新宿决战》那种复盘解说："
    "每一张配图后面跟一句中文说明，中性陈述、不抒情、不用第一人称、不加小标题。"
)

SEQUENCE_PROMPT = """下面是一条 81 秒动画短片（《咒术回战》涉谷事变：五条悟在地铁站展开 0.2 秒「无量空处」）按镜头切分后的逐帧识图结果。
请为每一帧产出一句**中文笔记**，输出 JSON 数组，每项 {"index": <帧序号>, "line": "<一句话>"}。

写「一句话」的规则（按优先级）：
1. 该帧画面上有字幕 -> 写成引用台词的格式：「<说话人>：「<字幕原文>」」。说话人用给你的 speaker 字段；
   若 speaker 是「不确定」，就写「字幕：「<原文>」」。字幕原文一字不改。
2. 该帧没有字幕 -> 用 action 字段改写成一句旁白式描述；可以结合前后帧补齐动作的来龙去脉，但**不得虚构画面上没有的信息**。
3. 相邻帧若在讲同一件事，句子之间要有推进感，不要机械重复同一句式；避免每句都以「五条悟」开头。
4. 每句 10~45 字，中文全角标点；不要写「这一帧」「图片」「如图」。
5. 转场帧写「转场：<描述>」。

另外，附带的日文 ASR 转写**不可靠**（含明显幻觉，例如把「無量空処」听成「有料空所」），
只在你能与字幕对得上时参考，对不上就完全忽略它，不要把它的话写进笔记。

只输出 JSON 数组，不要解释。
"""


def build_sequence_payload(frames: list, asr_text: str) -> str:
    lines = ["【逐帧识图结果】"]
    for f in frames:
        lines.append(
            f"- index={f['index']} t={f.get('time', 0):.2f}s "
            f"subtitle={f.get('subtitle', '')!r} speaker={f.get('speaker', '')!r} "
            f"conf={f.get('subtitle_confidence', 0)} "
            f"action={f.get('action', '')!r} scene={f.get('scene', '')!r} "
            f"chars={f.get('characters', [])} ontext={f.get('on_screen_text', [])}"
        )
    lines.append("")
    lines.append("【日文 ASR 转写（不可靠，仅供交叉核对）】")
    lines.append(asr_text or "(无)")
    return "\n".join(lines)
