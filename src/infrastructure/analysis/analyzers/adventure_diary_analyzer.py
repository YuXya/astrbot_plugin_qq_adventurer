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
        editable_manager=None,
    ):
        super().__init__(context, config_manager, editable_manager)
        self.domain_service = domain_service
        self.world_book_engine = WorldBookEngine(editable_manager=self.editable_manager)

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

        return self.editable_manager.render_prompt(
            "adventure_diary_prompt",
            {
                "player_name": nickname or card.get("target_name") or user_id or "unknown",
                "current_level": current_level,
                "profile_card_json": self._json_dump(card),
                "state_json": self._json_dump(state),
                "logs_text": self._format_logs(logs),
                "action": action,
                "world_book_text": world_book_text,
            },
        )

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
