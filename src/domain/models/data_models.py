from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ReincarnationCard:
    title: str
    subtitle: str
    target_name: str
    race: str
    class_name: str
    appearance: str
    personality: str
    talent: str
    stats: dict[str, str] = field(default_factory=dict)
    likes: list[str] = field(default_factory=list)
    quote: str = ""
    footer: str = ""
    avatar_url: str = ""
    avatar_caption: str = ""

    def to_text(self) -> str:
        stats_text = " / ".join(
            f"{key}: {value}" for key, value in self.stats.items() if value
        )
        likes_text = "、".join(self.likes)
        parts = [
            f"{self.title} - {self.subtitle}".strip(" -"),
            f"转生对象：{self.target_name}",
            f"种族：{self.race} / 职阶：{self.class_name}",
            f"外貌：{self.appearance}",
            f"性格：{self.personality}",
            f"天赋：{self.talent}",
        ]
        if stats_text:
            parts.append(f"能力值：{stats_text}")
        if likes_text:
            parts.append(f"喜欢：{likes_text}")
        if self.quote:
            parts.append(f"台词：{self.quote}")
        if self.footer:
            parts.append(self.footer)
        return "\n".join(part for part in parts if part)


@dataclass
class AdventureAnalysisResult:
    card: ReincarnationCard
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    raw_response: str = ""


@dataclass
class AdventureExecutionResult:
    success: bool
    card: ReincarnationCard | None = None
    image_path: str | None = None
    text: str = ""
    error: str | None = None
    raw_response: str = ""
