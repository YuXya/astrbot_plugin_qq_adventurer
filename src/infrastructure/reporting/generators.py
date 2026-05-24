from __future__ import annotations

import asyncio
import base64
import os
import time
from pathlib import Path
from typing import Any

from astrbot.api.star import StarTools

from ...domain.models.data_models import AdventureCard
from ...domain.repositories.card_repository import ICardGenerator
from ...utils.logger import logger
from .templates import HTMLTemplates


class ReportGenerator(ICardGenerator):
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.html_templates = HTMLTemplates()
        self._render_semaphore = asyncio.Semaphore(
            self.config_manager.get_t2i_max_concurrent()
        )

    async def generate_image_card(
        self,
        card: AdventureCard,
        html_render_func: Any,
    ) -> tuple[str | None, str | None]:
        html_content = self.html_templates.render_template(
            "card.html",
            card=card,
            choices=card.choices,
            status_items=list(card.status.items()),
        )
        if not html_content:
            return None, None

        async with self._render_semaphore:
            for image_options in self.config_manager.get_t2i_rendering_strategies():
                options = dict(image_options)
                if options.get("type") == "png":
                    options.pop("quality", None)
                try:
                    image_data = await html_render_func(
                        html_content,
                        {},
                        False,
                        options,
                    )
                    image_path = self._persist_image(image_data, options.get("type", "png"))
                    if image_path:
                        return image_path, html_content
                except Exception as exc:
                    logger.warning(f"HTML 转图片失败，尝试下一轮策略: {exc}")

        return None, html_content

    def _persist_image(self, image_data: object, image_type: object) -> str | None:
        if not image_data:
            return None

        if isinstance(image_data, str) and os.path.isfile(image_data):
            return image_data

        suffix = ".jpg" if str(image_type).lower() in {"jpg", "jpeg"} else ".png"
        output_dir = StarTools.get_data_dir() / "cards"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"adventure_{int(time.time() * 1000)}{suffix}"

        try:
            if isinstance(image_data, bytes):
                output_path.write_bytes(image_data)
                return str(output_path)

            if isinstance(image_data, str):
                data = image_data
                if data.startswith("base64://"):
                    data = data[len("base64://") :]
                elif data.startswith("data:image/"):
                    data = data.split(",", 1)[1]
                else:
                    logger.warning("html_render 返回了无法识别的字符串图片数据")
                    return None
                output_path.write_bytes(base64.b64decode(data))
                return str(output_path)
        except Exception as exc:
            logger.error(f"保存图片失败: {exc}", exc_info=True)

        return None

