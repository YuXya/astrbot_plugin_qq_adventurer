from __future__ import annotations

from ..models.data_models import AdventureCard, AdventureChoice


class AdventureDomainService:
    def __init__(self, max_choices: int = 3):
        self.max_choices = max(2, min(max_choices, 4))

    def normalize_card(self, raw: dict) -> AdventureCard:
        title = self._clean_text(raw.get("title"), "未命名冒险")
        subtitle = self._clean_text(raw.get("subtitle"), "新的旅途正在展开")
        scene = self._clean_text(raw.get("scene"), "你站在岔路前，空气里有未说出口的预感。")
        footer = self._clean_text(raw.get("footer"), "输入下一步行动，继续推进冒险。")

        choices = self._normalize_choices(raw.get("choices"))
        status = self._normalize_status(raw.get("status"))

        return AdventureCard(
            title=title[:32],
            subtitle=subtitle[:48],
            scene=scene[:420],
            choices=choices,
            status=status,
            footer=footer[:80],
        )

    def build_mock_card(self, theme: str) -> AdventureCard:
        return AdventureCard(
            title="边境旅人的第一夜",
            subtitle=f"主题：{theme}",
            scene=(
                "暮色落在旧驿站的木牌上。远处的林线像一堵黑色城墙，"
                "而你的口袋里只有一枚发烫的铜钥匙。酒馆老板压低声音说："
                "今晚月亮升起前，最好决定自己要相信谁。"
            ),
            choices=[
                AdventureChoice("A", "询问酒馆老板钥匙的来历", "低"),
                AdventureChoice("B", "趁夜进入森林寻找锁孔", "高"),
                AdventureChoice("C", "去马厩检查是否有人跟踪", "中"),
            ],
            status={"体力": "8/10", "金币": "12", "线索": "铜钥匙"},
            footer="选择一个行动，下一张卡片会继续故事。",
        )

    def _normalize_choices(self, raw_choices: object) -> list[AdventureChoice]:
        choices: list[AdventureChoice] = []
        if isinstance(raw_choices, list):
            for index, item in enumerate(raw_choices[: self.max_choices]):
                if not isinstance(item, dict):
                    continue
                label = self._clean_text(item.get("label"), chr(ord("A") + index))
                text = self._clean_text(item.get("text"), "")
                risk = self._clean_text(item.get("risk"), "未知")
                if text:
                    choices.append(
                        AdventureChoice(label=label[:4], text=text[:80], risk=risk[:12])
                    )

        while len(choices) < 2:
            label = chr(ord("A") + len(choices))
            fallback = "谨慎观察周围" if label == "A" else "向前迈出一步"
            choices.append(AdventureChoice(label, fallback, "未知"))

        return choices

    @staticmethod
    def _normalize_status(raw_status: object) -> dict[str, str]:
        if not isinstance(raw_status, dict):
            return {"体力": "10/10", "线索": "无"}
        result: dict[str, str] = {}
        for key, value in raw_status.items():
            clean_key = str(key).strip()
            clean_value = str(value).strip()
            if clean_key and clean_value:
                result[clean_key[:10]] = clean_value[:24]
            if len(result) >= 4:
                break
        return result or {"体力": "10/10", "线索": "无"}

    @staticmethod
    def _clean_text(value: object, default: str) -> str:
        if value is None:
            return default
        text = str(value).strip()
        return text if text else default

