from __future__ import annotations

import json

from ....domain.models.data_models import AdventureDiaryCard, TokenUsage
from ....domain.services.adventure_diary_domain_service import AdventureDiaryDomainService
from ....utils.logger import logger
from ...patch_books import PatchBookEngine
from ...world_book import WorldBookEngine
from ..utils.json_utils import parse_json_object_response
from ..utils.llm_utils import (
    call_provider_with_retry,
    extract_response_text,
    extract_token_usage,
)
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
        self.patch_book_engine = PatchBookEngine(editable_manager=self.editable_manager)

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
        cameo_memories: list[dict] | None = None,
        nearby_players: list[dict] | None = None,
        user_id: str | None = None,
        nickname: str | None = None,
        umo: str | None = None,
    ) -> tuple[AdventureDiaryCard | None, TokenUsage, str]:
        prompt = self.build_diary_prompt(
            action_text=action_text,
            profile=profile,
            state=state,
            logs=logs,
            cameo_memories=cameo_memories,
            nearby_players=nearby_players,
            user_id=user_id,
            nickname=nickname,
        )
        include_birth_fields = self._is_first_adventure(logs)
        system_prompt = self._build_diary_character_system_prompt(
            profile,
            include_birth_fields=include_birth_fields,
        )
        if self.config_manager.get_debug_mode():
            self._save_debug_file("diary_prompt", prompt)
            self._save_debug_file("diary_system_prompt", system_prompt)

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
        cameo_memories: list[dict] | None,
        nearby_players: list[dict] | None,
        user_id: str | None,
        nickname: str | None,
    ) -> str:
        include_birth_fields = self._is_first_adventure(logs)
        card = self._diary_profile_card(profile, include_birth_fields=include_birth_fields)
        current_level = self.domain_service.get_current_level(state)
        action = action_text.strip() or "玩家没有指定行动，请根据当前状态自由生成一次小冒险。"
        scan_parts = [
            "/异世界冒险",
            "异世界冒险",
            action,
            str(state.get("region", "")),
            str(state.get("location", "")),
            self._format_logs_for_scan(logs),
        ]
        world_book_text = self.world_book_engine.build_prompt_text(scan_parts).prompt_text
        supplement_text = self._join_optional_prompt_parts(
            [
                world_book_text,
                self.patch_book_engine.build_skill_prompt_text(scan_parts),
                self.patch_book_engine.build_status_prompt_text(state),
                self._format_nearby_players(nearby_players),
            ]
        )
        cameo_memories_text = self._format_cameo_memories(cameo_memories)
        prompt_template = self.editable_manager.get_prompt("adventure_diary_prompt")
        logs_text = self._format_logs(logs)
        if "{{cameo_memories_text}}" not in prompt_template:
            logs_text = self._join_optional_prompt_parts(
                [
                    logs_text,
                    "其他人与主角的交互：\n" + cameo_memories_text,
                ]
            )

        return self.editable_manager.render_text(
            prompt_template,
            {
                "player_name": nickname or card.get("target_name") or user_id or "unknown",
                "current_level": current_level,
                "profile_card_json": self._json_dump(card),
                "state_json": self._json_dump(state),
                "logs_text": logs_text,
                "cameo_memories_text": cameo_memories_text,
                "action": action,
                "supplement_text": supplement_text,
                "world_book_text": supplement_text,
            },
        )

    def _build_diary_character_system_prompt(
        self,
        profile: dict,
        include_birth_fields: bool = True,
    ) -> str:
        card = self._diary_profile_card(
            profile,
            include_birth_fields=include_birth_fields,
        )
        return self.editable_manager.render_prompt(
            "adventure_diary_system_prompt",
            {
                "target_name": self._card_text(card, "target_name", "无名冒险者"),
                "race": self._card_text(card, "race", "未知种族"),
                "class_name": self._card_text(card, "class_name", "新手冒险者"),
                "appearance": self._card_text(card, "appearance", "转生后的可爱异世界外貌"),
                "personality": self._card_text(card, "personality", "保留转生卡中的性格"),
                "talent": self._card_text(card, "talent", "尚未觉醒的天赋"),
                "birth_description": self._card_text(card, "birth_description", ""),
            },
        )

    @staticmethod
    def _diary_profile_card(
        profile: dict,
        include_birth_fields: bool = True,
    ) -> dict:
        card = profile.get("card", {}) if isinstance(profile, dict) else {}
        if not isinstance(card, dict):
            return {}
        if include_birth_fields:
            return dict(card)
        return {
            key: value
            for key, value in card.items()
            if key not in {"birth_description", "birth_region", "birth_location"}
        }

    @staticmethod
    def _is_first_adventure(logs: list[dict]) -> bool:
        return not any(
            isinstance(item, dict) and item.get("type") == "adventure_diary"
            for item in logs
        )

    @staticmethod
    def _json_dump(data: object) -> str:
        return json.dumps(data if data is not None else {}, ensure_ascii=False, indent=2)

    @staticmethod
    def _card_text(card: dict, key: str, fallback: str) -> str:
        if not isinstance(card, dict):
            return fallback
        value = str(card.get(key) or "").strip()
        return value or fallback

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
            region = item.get("region", "")
            line = f"{index}. {title}"
            if action:
                line += f"；行动：{action}"
            if region:
                line += f"；区域：{region}"
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

    @staticmethod
    def _format_cameo_memories(cameo_memories: list[dict] | None) -> str:
        if not cameo_memories:
            return "（暂无其他人与主角的交互。）"
        lines = []
        for index, item in enumerate(cameo_memories[-8:], start=1):
            source_name = item.get("source_target_name", "")
            title = item.get("title", "") or "其他人的记录"
            encounter = item.get("encounter", "")
            result = item.get("result", "")
            region = item.get("region", "")
            line = f"{index}. 来源：{source_name or '未知'}；标题：{title}"
            if region:
                line += f"；区域：{region}"
            if encounter:
                line += f"；遭遇：{encounter}"
            if result:
                line += f"；结算：{result}"
            lines.append(line[:360])
        return "\n".join(lines)

    @classmethod
    def _format_nearby_players(cls, nearby_players: list[dict] | None) -> str:
        if not nearby_players:
            return ""
        return (
            "该地区其他玩家：\n"
            + cls._json_dump(cls._public_nearby_players(nearby_players))
            + "\n以上玩家是同出生地区可客串 NPC。可以让他们以偶遇、传闻、同行、"
            "交易、目击者或短暂协助的方式自然出现；不要替他们决定永久性重大"
            "状态变化、死亡、失踪、残疾、重大财产损失或离开原本地区。"
        )

    @staticmethod
    def _public_nearby_players(nearby_players: list[dict]) -> list[dict]:
        return [
            {key: value for key, value in item.items() if not str(key).startswith("_")}
            for item in nearby_players
            if isinstance(item, dict)
        ]

    @staticmethod
    def _join_optional_prompt_parts(parts: list[str]) -> str:
        return "\n\n".join(str(part).strip() for part in parts if str(part).strip())
