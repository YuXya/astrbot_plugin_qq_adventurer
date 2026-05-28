from __future__ import annotations

from dataclasses import dataclass
from typing import Any


PROGRESS_KEYS = {"经验", "熟练度", "proficiency"}
LEVEL_KEYS = ("等级", "level", "Lv", "lv")
HIDDEN_STATE_KEYS = {"schema_version", "group_id", "user_id", "updated_at"}


@dataclass(frozen=True)
class ProgressItem:
    label: str
    level: int
    value: int
    percent: int


def build_progress_items(state: dict[str, Any], limit: int = 12) -> list[ProgressItem]:
    if not isinstance(state, dict):
        return []
    items: list[ProgressItem] = []
    if "level_exp" in state or "level" in state:
        items.append(
            ProgressItem(
                label="冒险等级",
                level=_int_value(state.get("level"), 1),
                value=_clamp_progress(state.get("level_exp")),
                percent=_clamp_progress(state.get("level_exp")),
            )
        )
    _collect_progress_items(state, [], items)
    return items[:limit]


def build_state_display_items(state: dict[str, Any], limit: int = 24) -> list[tuple[str, str]]:
    if not isinstance(state, dict):
        return []
    items: list[tuple[str, str]] = []
    for key, value in state.items():
        if key in HIDDEN_STATE_KEYS:
            continue
        _append_state_item(items, str(key), value)
    return items[:limit]


def state_label(label: str) -> str:
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


def _collect_progress_items(
    value: object,
    path: list[str],
    items: list[ProgressItem],
) -> None:
    if not isinstance(value, dict):
        return
    for key, child in value.items():
        key_text = str(key)
        if key_text in HIDDEN_STATE_KEYS:
            continue
        if key_text == "level_exp":
            continue
        child_path = [*path, key_text]
        if key_text in PROGRESS_KEYS:
            items.append(
                ProgressItem(
                    label=_progress_label(path),
                    level=_progress_level(value),
                    value=_clamp_progress(child),
                    percent=_clamp_progress(child),
                )
            )
            continue
        if isinstance(child, dict):
            _collect_progress_items(child, child_path, items)


def _append_state_item(
    items: list[tuple[str, str]],
    label: str,
    value: object,
) -> None:
    if _is_progress_leaf(label):
        return
    if isinstance(value, dict):
        if not value:
            items.append((state_label(label), "无"))
            return
        for child_key, child_value in value.items():
            child_label = f"{label}/{child_key}"
            if _is_progress_leaf(child_label) or str(child_key) in LEVEL_KEYS:
                continue
            _append_state_item(items, child_label, child_value)
        return
    if isinstance(value, list):
        display = "、".join(str(item) for item in value[:12]) if value else "无"
        if len(value) > 12:
            display += f" 等 {len(value)} 项"
        items.append((state_label(label), display))
        return
    items.append((state_label(label), str(value)))


def _progress_label(path: list[str]) -> str:
    for part in reversed(path):
        if part not in {"主角", "技能", "状态", "特质"}:
            return state_label(part)
    return state_label(path[-1]) if path else "进度"


def _progress_level(parent: dict[str, Any]) -> int:
    for key in LEVEL_KEYS:
        if key in parent:
            return max(1, _int_value(parent.get(key), 1))
    return 1


def _is_progress_leaf(label: str) -> bool:
    return (
        label == "level_exp"
        or label.endswith("/level_exp")
        or any(label.endswith(f"/{key}") for key in PROGRESS_KEYS)
    )


def _clamp_progress(value: object) -> int:
    return max(0, min(_int_value(value, 0), 99))


def _int_value(value: object, default: int) -> int:
    try:
        return int(float(value if value is not None else default))
    except Exception:
        return default
