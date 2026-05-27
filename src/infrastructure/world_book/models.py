from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class WorldBookEntry:
    id: str
    title: str = ""
    enabled: bool = True
    strategy: str = "keyword"
    keys: list[str] = field(default_factory=list)
    order: int = 100
    recursive: bool = True
    content: str = ""

    @classmethod
    def from_dict(cls, raw: dict, fallback_id: str) -> "WorldBookEntry":
        keys = raw.get("keys", [])
        if isinstance(keys, str):
            keys = [keys]
        if not isinstance(keys, list):
            keys = []

        try:
            order = int(raw.get("order", 100))
        except (TypeError, ValueError):
            order = 100

        return cls(
            id=str(raw.get("id") or fallback_id).strip(),
            title=str(raw.get("title") or "").strip(),
            enabled=bool(raw.get("enabled", True)),
            strategy=str(raw.get("strategy") or "keyword").strip().lower(),
            keys=[str(key).strip() for key in keys if str(key).strip()],
            order=order,
            recursive=raw.get("recursive", True) is not False,
            content=str(raw.get("content") or "").strip(),
        )


@dataclass(frozen=True)
class WorldBookMatchResult:
    entries: list[WorldBookEntry]
    prompt_text: str
