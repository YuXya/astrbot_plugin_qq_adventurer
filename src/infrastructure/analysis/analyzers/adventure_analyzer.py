from __future__ import annotations

from ....domain.models.data_models import ReincarnationCard
from ....domain.services.adventure_domain_service import AdventureDomainService
from .base_analyzer import BaseAnalyzer


class AdventureAnalyzer(BaseAnalyzer[ReincarnationCard]):
    def __init__(self, context, config_manager, domain_service: AdventureDomainService):
        super().__init__(context, config_manager)
        self.domain_service = domain_service

    def get_data_type(self) -> str:
        return "异世界转生人物卡"

    def build_prompt(
        self,
        theme: str,
        user_id: str | None,
        nickname: str | None,
        player_messages: list[str] | None = None,
    ) -> str:
        player_text = f"目标群友昵称：{nickname}" if nickname else f"目标群友ID：{user_id or 'unknown'}"
        messages_text = self._format_player_messages(player_messages)
        return f"""请根据目标群友最近的聊天发言，生成一张“异世界转生人物卡”。

触发命令：{theme}
{player_text}

目标群友最近发言：
{messages_text}

内容要求：
1. 只输出一个合法 JSON 对象，不要 Markdown，不要解释。
2. 必须根据聊天记录推断目标群友的性格、表达习惯和群聊气质；如果聊天记录不足，请明确按“玩具测试样例”生成。
3. 外貌必须是可可爱爱的异世界小萝莉风格：小只、圆润、软萌、轻小说人物卡感。
4. 性格可以多样：冷淡、嘴硬、活泼、毒舌、社恐、可靠、混沌、温柔都可以，但要和发言气质有关。
5. 字段要短，适合渲染到图片卡片。

JSON 格式：
{{
  "title": "异世界转生人物卡",
  "subtitle": "一句副标题",
  "target_name": "群友名称",
  "race": "转生种族",
  "class_name": "异世界职阶",
  "appearance": "可爱小萝莉外貌描述，60 到 160 字",
  "personality": "根据聊天记录推断出的性格，40 到 140 字",
  "talent": "一个和聊天风格有关的异世界天赋",
  "stats": {{"魔力": "A", "吐槽": "S", "幸运": "B", "可爱": "SS"}},
  "likes": ["喜欢物1", "喜欢物2", "喜欢物3"],
  "quote": "一句符合该角色的可爱台词",
  "footer": "一句底部说明"
}}"""

    def create_data_object(self, data: dict) -> ReincarnationCard:
        return self.domain_service.normalize_card(data)

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
