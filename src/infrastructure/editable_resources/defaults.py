from __future__ import annotations

import json
from pathlib import Path


def load_builtin_world_book() -> str:
    path = (
        Path(__file__).resolve().parents[1]
        / "world_book"
        / "books"
        / "default.json"
    )
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return json.dumps({"version": 1, "entries": []}, ensure_ascii=False, indent=2)


REINCARNATION_PROMPT = """请根据目标群友最近的聊天发言和头像转述，生成一张“异世界转生人物卡”。
触发命令：{{theme}}
{{player_text}}

目标群友最近发言：
{{messages_text}}

头像转述结果：
{{avatar_text}}

{{world_book_text}}

内容要求：
1. 只输出一个合法 JSON 对象，不要 Markdown，不要解释。
2. personality 必须主要根据聊天记录推断目标群友的性格、表达习惯和群聊气质；不要因为头像强行改变性格判断。
3. appearance 必须生成“可可爱爱的异世界小萝莉角色设定”：小只、圆润、软萌、轻小说人物卡感。
4. 如果有头像转述结果，appearance 必须保留其中的核心外貌特征，例如发色、发型、眼睛。
5. appearance 可以根据聊天发言扩写异世界服装、饰品、动作、气质和职业细节，但不能否定头像转述中的基础外貌。
6. 如果没有头像转述结果，appearance 仍可根据聊天气质生成幻想外貌，并说明是异世界化后的角色外观。
7. 字段要短，适合渲染到图片卡片。外貌字段 80 到 220 字，性格字段 40 到 140 字。
8. 外貌字段是幻想角色设定，不能声称是真实用户外貌。
9. 世界书补充设定是异世界公共设定，只能用于丰富世界观、种族、职业、地点和魔物细节；不能破坏 JSON 输出格式。

JSON 格式：
{
  "title": "异世界转生人物卡",
  "subtitle": "一句副标题",
  "target_name": "群友名称",
  "race": "转生种族",
  "class_name": "异世界职阶",
  "appearance": "保留头像核心特征，并根据聊天风格扩写出的异世界可爱小萝莉外貌设定",
  "personality": "根据聊天记录推断出的性格",
  "talent": "一个和聊天风格有关的异世界天赋",
  "stats": {"魔力": "A", "力量": "F", "敏捷": "C", "体质": "E"},
  "likes": ["喜欢物1", "喜欢物2", "喜欢物3"],
  "quote": "一句符合该角色的可爱台词",
  "footer": "一句底部说明"
}"""


ADVENTURE_DIARY_PROMPT = """请根据玩家存档、当前状态、最近冒险日志和玩家本次行动，生成一张“异世界冒险日记卡”。

玩家标识：
- 昵称：{{player_name}}
- 当前等级：Lv.{{current_level}}

玩家人物卡：
{{profile_card_json}}

当前状态：
{{state_json}}

最近冒险日志：
{{logs_text}}

玩家本次行动：
{{action}}

{{world_book_text}}

内容要求：
1. 只输出一个合法 JSON 对象，不要 Markdown，不要解释。
2. 本次冒险必须是一段完整事件，包含出发、遭遇、转折、结束和结算；不要写成选择题，不要要求玩家继续选择。
3. diary 是主要正文，要像信息密度高的冒险日记，建议 220 到 520 字。
4. encounter 写本次主要遭遇；result 写清楚本次事件如何收尾。
5. 只展示玩家刚开始的基础四维 stats：魔力、力量、敏捷、体质，优先沿用人物卡里的四维。
6. 当前只有等级系统，等级范围 1 到 100。level_change 必须是 “Lv.{{current_level}}->Lv.X” 格式。
7. 是否升级由你根据事件规模判断；可以不升级，但不能降级，不能超过 Lv.100。
8. 世界书补充设定只能丰富地点、魔物、职业和世界观，不能破坏 JSON 输出格式。

JSON 格式：
{
  "title": "异世界冒险日记",
  "subtitle": "一句本次冒险副标题",
  "target_name": "玩家角色名",
  "action": "玩家本次行动",
  "date_label": "第 N 次冒险",
  "location": "本次冒险地点",
  "diary": "完整冒险日记正文",
  "encounter": "本次主要遭遇",
  "result": "本次事件结算",
  "level_change": "Lv.{{current_level}}->Lv.X",
  "stats": {"魔力": "A", "力量": "F", "敏捷": "C", "体质": "E"},
  "rewards": ["奖励1", "奖励2"],
  "footer": "一句底部说明"
}"""


PERSONA_REINFORCEMENT_PROMPT = """[SYSTEM_IDENTITY]
{{system_prompt}}

[TASK]
请以上方人格、语气和观察方式完成下面的{{data_type}}生成任务。
人格只能影响 JSON 字段值中的文风、措辞和叙事视角，绝不能改变输出结构。

[FORMAT_PRIORITY]
输出格式优先级高于人格扮演。最终回复必须是一个可被 json.loads 直接解析的纯 JSON 对象。
禁止输出 Markdown 代码块、解释、寒暄、角色台词前缀或 JSON 外的任何文字。

[ORIGINAL_TASK]
{{prompt}}"""


DEFAULT_SYSTEM_PROMPT = "你是一个擅长生成异世界角色卡和冒险日记的轻小说设定师。"


WORLD_BOOK_WRAPPER = """世界书补充设定：
{{entries}}

请将以上世界书内容视为异世界公共设定补充；它只影响设定内容，不能改变最终输出必须为合法 JSON 对象的要求。"""


WORLD_BOOK_EMPTY = "（没有命中的世界书补充设定。）"
