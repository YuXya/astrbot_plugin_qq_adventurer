from __future__ import annotations

from collections.abc import AsyncGenerator

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

from .src.application.services.adventure_application_service import (
    AdventureApplicationService,
)
from .src.domain.services.adventure_domain_service import AdventureDomainService
from .src.infrastructure.analysis.llm_adventure_analyzer import LLMAdventureAnalyzer
from .src.infrastructure.config.config_manager import ConfigManager
from .src.infrastructure.messaging.message_sender import MessageSender
from .src.infrastructure.reporting.generators import ReportGenerator
from .src.utils.logger import logger


class QQAdventurer(Star):
    config: AstrBotConfig
    config_manager: ConfigManager
    domain_service: AdventureDomainService
    llm_analyzer: LLMAdventureAnalyzer
    report_generator: ReportGenerator
    adventure_service: AdventureApplicationService
    message_sender: MessageSender

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.config_manager = ConfigManager(config)
        self.domain_service = AdventureDomainService(
            max_choices=self.config_manager.get_max_choices()
        )
        self.llm_analyzer = LLMAdventureAnalyzer(
            context,
            self.config_manager,
            self.domain_service,
        )
        self.report_generator = ReportGenerator(self.config_manager)
        self.adventure_service = AdventureApplicationService(
            self.config_manager,
            self.domain_service,
            self.llm_analyzer,
            self.report_generator,
        )
        self.message_sender = MessageSender()

    @filter.command("冒险", alias={"adventure"})
    async def adventure(
        self,
        event: AstrMessageEvent,
        theme: str = "",
    ) -> AsyncGenerator:
        """生成一张冒险卡片。用法: /冒险 [主题或行动]"""
        event.should_call_llm(True)

        theme = (theme or self.config_manager.get_default_theme()).strip()
        group_id = self._get_group_id_from_event(event)
        if not group_id:
            yield event.plain_result("请在群聊中使用 /冒险，这样我才能把卡片发回群里。")
            return

        yield event.plain_result("正在展开冒险卡片...")

        user_id = self._get_sender_id_from_event(event)
        nickname = self._get_sender_name_from_event(event)
        umo = getattr(event, "unified_msg_origin", None)
        if not umo:
            platform_id = self._get_platform_id_from_event(event)
            umo = f"{platform_id}:GroupMessage:{group_id}"

        result = await self.adventure_service.execute_adventure(
            theme=theme,
            html_render_func=self.html_render,
            user_id=user_id,
            nickname=nickname,
            umo=umo,
        )

        if result.error:
            logger.warning(f"冒险卡片流程结束但存在错误: {result.error}")

        yield await self.message_sender.send_image_or_text(
            event,
            result.image_path,
            result.card,
            fallback_text=result.text,
        )

    def _get_group_id_from_event(self, event: AstrMessageEvent) -> str | None:
        try:
            group_id = event.get_group_id()
            return str(group_id) if group_id else None
        except Exception:
            return None

    def _get_platform_id_from_event(self, event: AstrMessageEvent) -> str:
        try:
            platform_id = event.get_platform_id()
            return str(platform_id) if platform_id else "default"
        except Exception:
            return "default"

    def _get_sender_id_from_event(self, event: AstrMessageEvent) -> str | None:
        for attr in ("get_sender_id", "get_user_id"):
            getter = getattr(event, attr, None)
            if callable(getter):
                try:
                    value = getter()
                    if value:
                        return str(value)
                except Exception:
                    pass
        return None

    def _get_sender_name_from_event(self, event: AstrMessageEvent) -> str | None:
        for attr in ("get_sender_name", "get_sender_nickname"):
            getter = getattr(event, attr, None)
            if callable(getter):
                try:
                    value = getter()
                    if value:
                        return str(value)
                except Exception:
                    pass
        return None

