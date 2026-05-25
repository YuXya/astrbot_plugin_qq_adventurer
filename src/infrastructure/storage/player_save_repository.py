from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from astrbot.api.star import StarTools

from ...domain.models.data_models import ReincarnationCard
from ...utils.logger import logger


class PlayerSaveRepository:
    def __init__(self, plugin_name: str = "astrbot_plugin_qq_adventurer"):
        self.root_dir = StarTools.get_data_dir(plugin_name) / "saves"

    def save_reincarnation(
        self,
        group_id: str,
        user_id: str,
        card: ReincarnationCard,
        nickname: str | None = None,
    ) -> Path:
        user_dir = self.get_user_dir(group_id, user_id)
        user_dir.mkdir(parents=True, exist_ok=True)

        now = self._now_ms()
        profile = {
            "schema_version": 1,
            "group_id": str(group_id),
            "user_id": str(user_id),
            "nickname": nickname or card.target_name,
            "created_at": now,
            "updated_at": now,
            "card": self._to_jsonable(card),
        }
        state = {
            "schema_version": 1,
            "group_id": str(group_id),
            "user_id": str(user_id),
            "updated_at": now,
            "location": "转生大厅",
            "hp": 100,
            "mp": 100,
            "gold": 0,
            "inventory": [],
            "quests": [],
            "flags": {},
        }

        profile_path = user_dir / "profile.json"
        state_path = user_dir / "state.json"
        self._atomic_write_json(profile_path, profile)
        if not state_path.exists():
            self._atomic_write_json(state_path, state)
        else:
            self._touch_state_updated_at(state_path, now)

        self.append_log(
            group_id,
            user_id,
            {
                "type": "reincarnation",
                "message": "完成异世界转生",
                "created_at": now,
                "title": card.title,
                "target_name": card.target_name,
            },
        )
        return user_dir

    def append_log(self, group_id: str, user_id: str, record: dict[str, Any]) -> None:
        user_dir = self.get_user_dir(group_id, user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        log_path = user_dir / "adventure_log.jsonl"
        payload = dict(record)
        payload.setdefault("created_at", self._now_ms())
        with log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def get_user_dir(self, group_id: str, user_id: str) -> Path:
        safe_group = self._safe_id(group_id)
        safe_user = self._safe_id(user_id)
        return self.root_dir / "groups" / safe_group / "users" / safe_user

    def list_saves(self) -> list[dict[str, Any]]:
        groups_dir = self.root_dir / "groups"
        if not groups_dir.exists():
            return []

        saves: list[dict[str, Any]] = []
        for group_dir in sorted(p for p in groups_dir.iterdir() if p.is_dir()):
            users_dir = group_dir / "users"
            if not users_dir.exists():
                continue
            for user_dir in sorted(p for p in users_dir.iterdir() if p.is_dir()):
                profile = self._read_json(user_dir / "profile.json")
                state = self._read_json(user_dir / "state.json")
                saves.append(
                    {
                        "group_id": group_dir.name,
                        "user_id": user_dir.name,
                        "nickname": profile.get("nickname", ""),
                        "target_name": profile.get("card", {}).get("target_name", ""),
                        "race": profile.get("card", {}).get("race", ""),
                        "class_name": profile.get("card", {}).get("class_name", ""),
                        "location": state.get("location", ""),
                        "updated_at": max(
                            int(profile.get("updated_at", 0) or 0),
                            int(state.get("updated_at", 0) or 0),
                        ),
                    }
                )
        return saves

    def read_save_detail(self, group_id: str, user_id: str) -> dict[str, Any] | None:
        user_dir = self.get_user_dir(group_id, user_id)
        if not user_dir.exists():
            return None
        return {
            "group_id": self._safe_id(group_id),
            "user_id": self._safe_id(user_id),
            "profile": self._read_json(user_dir / "profile.json"),
            "state": self._read_json(user_dir / "state.json"),
            "logs": self._read_recent_logs(user_dir / "adventure_log.jsonl", limit=80),
        }

    def _touch_state_updated_at(self, state_path: Path, now: int) -> None:
        state = self._read_json(state_path)
        if not state:
            return
        state["updated_at"] = now
        self._atomic_write_json(state_path, state)

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            if not path.exists():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning(f"读取存档 JSON 失败: {path} {exc}")
            return {}

    def _read_recent_logs(self, path: Path, limit: int) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        except Exception as exc:
            logger.warning(f"读取冒险日志失败: {path} {exc}")
            return []

        logs: list[dict[str, Any]] = []
        for line in lines:
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    logs.append(item)
            except json.JSONDecodeError:
                continue
        return logs

    @staticmethod
    def _safe_id(value: object) -> str:
        text = str(value or "unknown").strip()
        text = re.sub(r"[^0-9A-Za-z_.-]+", "_", text)
        return text[:80] or "unknown"

    @staticmethod
    def _to_jsonable(value: object) -> Any:
        if is_dataclass(value):
            return asdict(value)
        return value

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)
