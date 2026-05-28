from __future__ import annotations

import asyncio
import base64
import os
import time
from typing import Any

from astrbot.api.star import StarTools

from ...domain.models.data_models import AdventureDiaryCard, ReincarnationCard
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
        card: ReincarnationCard,
        html_render_func: Any,
    ) -> tuple[str | None, str | None]:
        html_content = self.html_templates.render_template(
            "card.html",
            card=card,
            stats_items=list(card.stats.items()),
            likes=card.likes,
            avatar_url=card.avatar_url,
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

    async def generate_diary_image_card(
        self,
        card: AdventureDiaryCard,
        html_render_func: Any,
    ) -> tuple[str | None, str | None]:
        html_content = self.html_templates.render_template(
            "adventure_diary.html",
            card=card,
            stats_items=list(card.stats.items()),
            changes=card.changes,
            state_items=self._state_display_items(card.state_snapshot),
            avatar_url=card.avatar_url,
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
                    image_path = self._persist_image(
                        image_data,
                        options.get("type", "png"),
                        prefix="adventure_diary",
                    )
                    if image_path:
                        return image_path, html_content
                except Exception as exc:
                    logger.warning(f"冒险日记 HTML 转图片失败，尝试下一轮策略: {exc}")

        return None, html_content

    def _persist_image(
        self,
        image_data: object,
        image_type: object,
        prefix: str = "reincarnation",
    ) -> str | None:
        if not image_data:
            return None

        if isinstance(image_data, str) and os.path.isfile(image_data):
            return image_data

        suffix = ".jpg" if str(image_type).lower() in {"jpg", "jpeg"} else ".png"
        output_dir = StarTools.get_data_dir() / "cards"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{prefix}_{int(time.time() * 1000)}{suffix}"

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

    def _state_display_items(self, state: dict[str, Any]) -> list[tuple[str, str]]:
        if not isinstance(state, dict):
            return []
        hidden_keys = {"schema_version", "group_id", "user_id", "updated_at"}
        items: list[tuple[str, str]] = []
        for key, value in state.items():
            if key in hidden_keys:
                continue
            self._append_state_item(items, str(key), value)
        return items

    def _append_state_item(
        self,
        items: list[tuple[str, str]],
        label: str,
        value: object,
    ) -> None:
        if isinstance(value, dict):
            if not value:
                items.append((self._state_label(label), "无"))
                return
            for child_key, child_value in value.items():
                self._append_state_item(items, f"{label}/{child_key}", child_value)
            return
        if isinstance(value, list):
            display = "、".join(str(item) for item in value[:6]) if value else "无"
            if len(value) > 6:
                display += f" 等 {len(value)} 项"
            items.append((self._state_label(label), display))
            return
        suffix = "%"
        if label.endswith("/经验") or label.endswith("/熟练度") or label == "level_exp":
            items.append((self._state_label(label), f"{value}{suffix}"))
            return
        items.append((self._state_label(label), str(value)))

    @staticmethod
    def _state_label(label: str) -> str:
        labels = {
            "level": "等级",
            "level_exp": "等级经验",
            "hp": "HP",
            "mp": "MP",
            "gold": "金币",
            "inventory": "物品",
            "skills": "技能",
            "quests": "任务",
            "flags": "标记",
        }
        return labels.get(label, label)
