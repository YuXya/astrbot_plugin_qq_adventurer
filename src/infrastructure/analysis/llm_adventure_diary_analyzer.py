from __future__ import annotations

from ...domain.models.data_models import AdventureDiaryAnalysisResult
from ...domain.services.adventure_diary_domain_service import AdventureDiaryDomainService
from .analyzers.adventure_diary_analyzer import AdventureDiaryAnalyzer


class LLMAdventureDiaryAnalyzer:
    def __init__(self, context, config_manager, domain_service: AdventureDiaryDomainService):
        self.analyzer = AdventureDiaryAnalyzer(context, config_manager, domain_service)

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
    ) -> AdventureDiaryAnalysisResult:
        card, usage, raw_response = await self.analyzer.analyze_diary(
            action_text=action_text,
            profile=profile,
            state=state,
            logs=logs,
            user_id=user_id,
            nickname=nickname,
            umo=umo,
        )
        if card is None:
            raise ValueError("LLM 响应无法解析为异世界冒险日记卡 JSON")
        return AdventureDiaryAnalysisResult(
            card=card,
            token_usage=usage,
            raw_response=raw_response,
        )
