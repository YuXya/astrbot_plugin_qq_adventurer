from __future__ import annotations

import json

from ....domain.models.data_models import AdventureDiaryCard, TokenUsage
from ....domain.services.adventure_diary_domain_service import AdventureDiaryDomainService
from ...world_book import WorldBookEngine
from ..utils.json_utils import parse_json_object_response
from ..utils.llm_utils import (
    call_provider_with_retry,
    extract_response_text,
    extract_token_usage,
)
from ....utils.logger import logger
from .base_analyzer import BaseAnalyzer


class AdventureDiaryAnalyzer(BaseAnalyzer[AdventureDiaryCard]):
    def __init__(
        self,
        context,
        config_manager,
        domain_service: AdventureDiaryDomainService,
    ):
        super().__init__(context, config_manager)
        self.domain_service = domain_service
        self.world_book_engine = WorldBookEngine()

    def get_data_type(self) -> str:
        return "异世界冒险日记卡"

    def build_prompt(
        self,
        theme: str,
        user_id: str | None,
        nickname: str | None,
        player_messages: list[str] | None = None,
        avatar_caption: str | None = None,
    ) -> str:
        return ""

    def create_data_object(
        self,
        data: dict,
        avatar_url: str | None = None,
        avatar_caption: str | None = None,
    ) -> AdventureDiaryCard:
        return self.domain_service.normalize_card(data, {}, {}, "")

    async def analyze_diary(
        self,
        *,
        action_text: str,
        profile: dict,
        state: dict,
        logs: list[dict],
        user_id: str | None = None,
        nickname: str | None = None,
        umo: str | None = None,
    ) -> tuple[AdventureDiaryCard | None, TokenUsage, str]:
        prompt = self.build_diary_prompt(
            action_text=action_text,
            profile=profile,
            state=state,
            logs=logs,
            user_id=user_id,
            nickname=nickname,
        )
        system_prompt = await self._build_system_prompt(umo)
        prompt = self._apply_persona_reinforcement(prompt, system_prompt)
        if self.config_manager.get_debug_mode():
            self._save_debug_file("diary_prompt", prompt)

        response = await call_provider_with_retry(
            self.context,
            self.config_manager,
            prompt=prompt,
            umo=umo,
            system_prompt=system_prompt,
        )
        result_text = extract_response_text(response)
        if self.config_manager.get_debug_mode():
            self._save_debug_file("diary_response", result_text)

        usage_dict = extract_token_usage(response)
        token_usage = TokenUsage(
            prompt_tokens=usage_dict["prompt_tokens"],
            completion_tokens=usage_dict["completion_tokens"],
            total_tokens=usage_dict["total_tokens"],
        )

        success, parsed, error = parse_json_object_response(result_text)
        if not success or not parsed:
            logger.error(f"{self.get_data_type()} JSON 解析失败: {error}")
            return None, token_usage, result_text

        return (
            self.domain_service.normalize_card(parsed, profile, state, action_text),
            token_usage,
            result_text,
        )

    def build_diary_prompt(
        self,
        *,
        action_text: str,
        profile: dict,
        state: dict,
        logs: list[dict],
        user_id: str | None,
        nickname: str | None,
    ) -> str:
        card = profile.get("card", {}) if isinstance(profile, dict) else {}
        current_level = self.domain_service.get_current_level(state)
        action = action_text.strip() or "玩家没有指定行动，请根据当前状态自由生成一次小冒险。"
        scan_parts = [
            action,
            str(state.get("location", "")),
            self._format_logs_for_scan(logs),
        ]
        world_book_text = self.world_book_engine.build_prompt_text(scan_parts).prompt_text

        return f"""请根据玩家存档、当前状态、最近冒险日志和玩家本次行动，生成一张“异世界冒险日记卡”。

玩家标识：
- 昵称：{nickname or card.get("target_name") or user_id or "unknown"}
- 当前等级：Lv.{current_level}

玩家人物卡：
{self._json_dump(card)}

当前状态：
{self._json_dump(state)}

最近冒险日志：
{self._format_logs(logs)}

玩家本次行动：
{action}

{world_book_text}

内容要求：
1. 只输出一个合法 JSON 对象，不要 Markdown，不要解释。
2. 本次冒险必须是一段完整事件，包含出发、遭遇、转折、结束和结算；不要写成选择题，不要要求玩家继续选择。
3. diary 是主要正文，要像信息密度高的冒险日记，建议 220 到 520 字。
4. encounter 写本次主要遭遇；result 写清楚本次事件如何收尾。
5. 只展示玩家刚开始的基础四维 stats：魔力、力量、敏捷、体质，优先沿用人物卡里的四维。
6. 当前只有等级系统，等级范围 1 到 100。level_change 必须是 “Lv.{current_level}->Lv.X” 格式。
7. 是否升级由你根据事件规模判断；可以不升级，但不能降级，不能超过 Lv.100。
8. 世界书补充设定只能丰富地点、魔物、职业和世界观，不能破坏 JSON 输出格式。

JSON 格式：
{{
  "title": "异世界冒险日记",
  "subtitle": "一句本次冒险副标题",
  "target_name": "玩家角色名",
  "action": "玩家本次行动",
  "date_label": "第 N 次冒险",
  "location": "本次冒险地点",
  "diary": "完整冒险日记正文",
  "encounter": "本次主要遭遇",
  "result": "本次事件结算",
  "level_change": "Lv.{current_level}->Lv.X",
  "stats": {{"魔力": "A", "力量": "F", "敏捷": "C", "体质": "E"}},
  "rewards": ["奖励1", "奖励2"],
  "footer": "一句底部说明"
}}"""

    @staticmethod
    def _json_dump(data: object) -> str:
        return json.dumps(data if data is not None else {}, ensure_ascii=False, indent=2)

    @staticmethod
    def _format_logs(logs: list[dict]) -> str:
        if not logs:
            return "（暂无冒险日志。）"
        lines = []
        for index, item in enumerate(logs[-8:], start=1):
            title = item.get("title") or item.get("message") or item.get("type") or "记录"
            action = item.get("action", "")
            result = item.get("result", "")
            level = item.get("level_change", "")
            line = f"{index}. {title}"
            if action:
                line += f"；行动：{action}"
            if result:
                line += f"；结果：{result}"
            if level:
                line += f"；等级：{level}"
            lines.append(line[:260])
        return "\n".join(lines)

    @staticmethod
    def _format_logs_for_scan(logs: list[dict]) -> str:
        return "\n".join(
            str(item.get("action") or item.get("result") or item.get("title") or "")
            for item in logs[-8:]
        )
