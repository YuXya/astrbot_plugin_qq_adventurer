from __future__ import annotations

from typing import Any

from ...domain.models.data_models import AdventureDiaryExecutionResult
from ...domain.services.adventure_diary_domain_service import AdventureDiaryDomainService
from ...utils.logger import logger


class AdventureDiaryApplicationService:
    def __init__(
        self,
        config_manager: Any,
        domain_service: AdventureDiaryDomainService,
        llm_analyzer: Any,
        card_generator: Any,
        save_repository: Any,
    ):
        self.config_manager = config_manager
        self.domain_service = domain_service
        self.llm_analyzer = llm_analyzer
        self.card_generator = card_generator
        self.save_repository = save_repository

    async def execute_diary(
        self,
        *,
        group_id: str,
        user_id: str,
        nickname: str | None,
        action_text: str,
        umo: str | None,
        html_render_func,
    ) -> AdventureDiaryExecutionResult:
        try:
            save_data = self.save_repository.load_player_save(group_id, user_id)
            if not save_data:
                return AdventureDiaryExecutionResult(
                    success=False,
                    text="还没有你的异世界转生存档，请先使用 /异世界转生 建档。",
                    error="player_save_not_found",
                )

            profile = save_data.get("profile", {})
            state = save_data.get("state", {})
            logs = save_data.get("logs", [])
            analysis = await self.llm_analyzer.analyze_diary(
                action_text=action_text,
                profile=profile,
                state=state,
                logs=logs,
                user_id=user_id,
                nickname=nickname,
                umo=umo,
            )
            card = analysis.card

            current_level = self.domain_service.get_current_level(state)
            new_level = self.domain_service.parse_level_after(
                card.level_change,
                fallback=current_level,
            )
            self.save_repository.save_adventure_result(
                group_id,
                user_id,
                card,
                new_level,
            )

            image_path, _html = await self.card_generator.generate_diary_image_card(
                card,
                html_render_func,
            )
            if not image_path:
                return AdventureDiaryExecutionResult(
                    success=False,
                    card=card,
                    text=card.to_text(),
                    error="图片渲染失败，已回退文本。",
                    raw_response=analysis.raw_response,
                )

            return AdventureDiaryExecutionResult(
                success=True,
                card=card,
                image_path=image_path,
                text=card.to_text(),
                raw_response=analysis.raw_response,
            )
        except Exception as exc:
            logger.error(f"执行异世界冒险日记流程失败: {exc}", exc_info=True)
            return AdventureDiaryExecutionResult(
                success=False,
                text=f"异世界冒险日记生成失败：{exc}",
                error=str(exc),
            )
