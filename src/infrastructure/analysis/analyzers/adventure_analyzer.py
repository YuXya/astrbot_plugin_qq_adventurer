from __future__ import annotations

from ....domain.models.data_models import AdventureCard
from ....domain.services.adventure_domain_service import AdventureDomainService
from .base_analyzer import BaseAnalyzer


class AdventureAnalyzer(BaseAnalyzer[AdventureCard]):
    def __init__(self, context, config_manager, domain_service: AdventureDomainService):
        super().__init__(context, config_manager)
        self.domain_service = domain_service

    def get_data_type(self) -> str:
        return "冒险卡片"

    def build_prompt(self, theme: str, user_id: str | None, nickname: str | None) -> str:
        max_choices = self.config_manager.get_max_choices()
        player_text = f"玩家昵称：{nickname}" if nickname else f"玩家ID：{user_id or 'unknown'}"
        return f"""请根据用户给出的主题生成一张互动冒险卡片。

主题：{theme}
{player_text}

严格要求：
1. 只输出一个合法 JSON 对象，不要 Markdown，不要解释。
2. 文风要有画面感，但每个字段保持简短，适合渲染到图片卡片。
3. choices 数量为 2 到 {max_choices} 个。
4. status 是一个对象，放 2 到 4 个短状态，例如体力、金币、线索、地点。

JSON 格式：
{{
  "title": "卡片标题",
  "subtitle": "一句副标题",
  "scene": "当前场景描述，120 到 220 字",
  "choices": [
    {{"label": "A", "text": "行动选项", "risk": "低"}},
    {{"label": "B", "text": "行动选项", "risk": "中"}}
  ],
  "status": {{"体力": "10/10", "线索": "无"}},
  "footer": "一句结尾提示"
}}"""

    def create_data_object(self, data: dict) -> AdventureCard:
        return self.domain_service.normalize_card(data)

