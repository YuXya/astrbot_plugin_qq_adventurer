from __future__ import annotations

from ....domain.models.data_models import ReincarnationCard
from ....domain.services.adventure_domain_service import AdventureDomainService
from ...world_book import WorldBookEngine
from .base_analyzer import BaseAnalyzer


class AdventureAnalyzer(BaseAnalyzer[ReincarnationCard]):
    def __init__(
        self,
        context,
        config_manager,
        domain_service: AdventureDomainService,
        editable_manager=None,
    ):
        super().__init__(context, config_manager, editable_manager)
        self.domain_service = domain_service
        self.world_book_engine = WorldBookEngine(editable_manager=self.editable_manager)

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

        return self.editable_manager.render_prompt(
            "reincarnation_prompt",
            {
                "theme": theme,
                "player_text": player_text,
                "messages_text": messages_text,
                "avatar_text": avatar_text,
                "world_book_text": world_book_text,
            },
        )

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
