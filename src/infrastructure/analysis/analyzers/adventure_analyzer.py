from __future__ import annotations

from ....domain.models.data_models import ReincarnationCard
from ....domain.services.adventure_domain_service import AdventureDomainService
from ...world_book import WorldBookEngine
from .base_analyzer import BaseAnalyzer


class AdventureAnalyzer(BaseAnalyzer[ReincarnationCard]):
    def __init__(self, context, config_manager, domain_service: AdventureDomainService):
        super().__init__(context, config_manager)
        self.domain_service = domain_service
        self.world_book_engine = WorldBookEngine()

    def get_data_type(self) -> str:
        return "异世界转生人物卡"

    def build_prompt(
        self,
        theme: str,
        user_id: str | None,
        nickname: str | None,
        player_messages: list[str] | None = None,
        avatar_caption: str | None = None,
    ) -> str:
        player_text = (
            f"目标群友昵称：{nickname}"
            if nickname
            else f"目标群友ID：{user_id or 'unknown'}"
        )
        messages_text = self._format_player_messages(player_messages)
        avatar_text = self._format_avatar_caption(avatar_caption)
        world_book_text = self.world_book_engine.build_prompt_text(
            player_messages
        ).prompt_text

        return f"""请根据目标群友最近的聊天发言和头像转述，生成一张“异世界转生人物卡”。
触发命令：{theme}
{player_text}

目标群友最近发言：
{messages_text}

头像转述结果：
{avatar_text}

{world_book_text}

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
{{
  "title": "异世界转生人物卡",
  "subtitle": "一句副标题",
  "target_name": "群友名称",
  "race": "转生种族",
  "class_name": "异世界职阶",
  "appearance": "保留头像核心特征，并根据聊天风格扩写出的异世界可爱小萝莉外貌设定",
  "personality": "根据聊天记录推断出的性格",
  "talent": "一个和聊天风格有关的异世界天赋",
  "stats": {{"魔力": "A", "力量": "F", "敏捷": "C", "体质": "E"}},
  "likes": ["喜欢物1", "喜欢物2", "喜欢物3"],
  "quote": "一句符合该角色的可爱台词",
  "footer": "一句底部说明"
}}"""

    def create_data_object(
        self,
        data: dict,
        avatar_url: str | None = None,
        avatar_caption: str | None = None,
    ) -> ReincarnationCard:
        return self.domain_service.normalize_card(data, avatar_url, avatar_caption)

    @staticmethod
    def _format_player_messages(player_messages: list[str] | None) -> str:
        if not player_messages:
            return "（未读取到足够聊天记录，本次按玩具测试样例生成。）"

        lines = []
        for index, message in enumerate(player_messages[-30:], start=1):
            cleaned = str(message).replace("\n", " ").strip()
            if cleaned:
                lines.append(f"{index}. {cleaned[:160]}")
        return "\n".join(lines) or "（未读取到足够聊天记录，本次按玩具测试样例生成。）"

    @staticmethod
    def _format_avatar_caption(avatar_caption: str | None) -> str:
        caption = str(avatar_caption or "").strip()
        if not caption:
            return "（未启用头像转述，或头像转述失败。本次不参考头像外貌。）"
        return caption[:240]
