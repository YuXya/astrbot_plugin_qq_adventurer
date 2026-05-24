from __future__ import annotations

from typing import Any

from ...utils.logger import logger


class QQAvatarService:
    USER_AVATAR_HD_TEMPLATE = (
        "https://q.qlogo.cn/headimg_dl?dst_uin={user_id}&spec=640&img_type=jpg"
    )

    def __init__(self, context: Any, config_manager: Any):
        self.context = context
        self.config_manager = config_manager

    def build_avatar_url(self, user_id: str | None) -> str:
        user_id = str(user_id or "").strip()
        if not user_id or not user_id.isdigit():
            return ""
        return self.USER_AVATAR_HD_TEMPLATE.format(user_id=user_id)

    async def describe_avatar(self, avatar_url: str) -> str:
        if not avatar_url or not self.config_manager.get_enable_avatar_caption():
            return ""

        provider_id = self.config_manager.get_vision_provider_id()
        if not provider_id:
            logger.info("[Avatar] 未配置视觉 Provider，跳过头像转述")
            return ""

        try:
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=self.config_manager.get_avatar_caption_prompt(),
                image_urls=[avatar_url],
            )
            caption = str(getattr(response, "completion_text", "") or "").strip()
            if caption:
                logger.info(f"[Avatar] 头像转述成功，caption_len={len(caption)}")
                return caption[:240]
        except Exception as exc:
            logger.warning(f"[Avatar] 头像转述失败，继续生成卡片: {exc}")

        return ""
