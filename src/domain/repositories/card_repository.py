from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models.data_models import AdventureCard


class ICardGenerator(ABC):
    @abstractmethod
    async def generate_image_card(
        self,
        card: AdventureCard,
        html_render_func: Any,
    ) -> tuple[str | None, str | None]:
        pass

