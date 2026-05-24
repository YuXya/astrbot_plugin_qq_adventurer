from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class AdventureChoice:
    label: str
    text: str
    risk: str = "未知"


@dataclass
class AdventureCard:
    title: str
    subtitle: str
    scene: str
    choices: list[AdventureChoice] = field(default_factory=list)
    status: dict[str, str] = field(default_factory=dict)
    footer: str = ""

    def to_text(self) -> str:
        choice_lines = [
            f"{choice.label}. {choice.text}（风险：{choice.risk}）"
            for choice in self.choices
        ]
        status_text = " / ".join(
            f"{key}: {value}" for key, value in self.status.items() if value
        )
        parts = [
            f"{self.title} - {self.subtitle}".strip(" -"),
            self.scene,
            "\n".join(choice_lines),
        ]
        if status_text:
            parts.append(status_text)
        if self.footer:
            parts.append(self.footer)
        return "\n\n".join(part for part in parts if part)


@dataclass
class AdventureAnalysisResult:
    card: AdventureCard
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    raw_response: str = ""


@dataclass
class AdventureExecutionResult:
    success: bool
    card: AdventureCard | None = None
    image_path: str | None = None
    text: str = ""
    error: str | None = None
    raw_response: str = ""

