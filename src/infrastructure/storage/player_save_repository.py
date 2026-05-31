from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from astrbot.api.star import StarTools

from ...domain.models.data_models import AdventureDiaryCard, ReincarnationCard
from ...utils.logger import logger
from .state_progress import PROGRESS_KEYS


class PlayerSaveRepository:
    SOURCE_FILE_NAMES = {
        "index.json",
        "profile.json",
        "state.json",
        "adventure_log.jsonl",
        "cameo_memory.jsonl",
    }

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
            "level": 1,
            "level_exp": 0,
            "region": card.birth_region or "未知区域",
            "location": card.birth_location or "醒来的地方",
            "hp": 100,
            "mp": 100,
            "gold": 0,
            "inventory": [],
            "skills": {},
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
            state = self._read_json(state_path)

        self._write_player_index(
            group_id=group_id,
            user_id=user_id,
            target_name=card.target_name,
            region=state.get("region") or card.birth_region,
            location=state.get("location") or card.birth_location,
            updated_at=now,
        )

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

    def load_player_save(
        self,
        group_id: str,
        user_id: str,
        log_limit: int = 0,
    ) -> dict[str, Any] | None:
        user_dir = self.get_user_dir(group_id, user_id)
        profile_path = user_dir / "profile.json"
        if not profile_path.exists():
            return None

        state_path = user_dir / "state.json"
        profile = self._read_json(profile_path)
        state = self._read_json(state_path)
        if not state:
            now = self._now_ms()
            state = {
                "schema_version": 1,
                "group_id": str(group_id),
                "user_id": str(user_id),
                "updated_at": now,
                "level": 1,
                "level_exp": 0,
                "region": "转生大厅",
                "location": "转生大厅",
                "hp": 100,
                "mp": 100,
                "gold": 0,
                "inventory": [],
                "skills": {},
                "quests": [],
                "flags": {},
            }
            self._atomic_write_json(state_path, state)
        else:
            changed = False
            if "level" not in state:
                state["level"] = 1
                changed = True
            if "level_exp" not in state:
                state["level_exp"] = 0
                changed = True
            if "region" not in state:
                state["region"] = state.get("location") or "未知区域"
                changed = True
            if "skills" not in state or not isinstance(state.get("skills"), dict):
                state["skills"] = {}
                changed = True
            if changed:
                self._atomic_write_json(state_path, state)

        return {
            "group_id": self._safe_id(group_id),
            "user_id": self._safe_id(user_id),
            "profile": profile,
            "state": state,
            "logs": self._read_recent_logs(
                user_dir / "adventure_log.jsonl",
                limit=log_limit,
            ),
            "cameo_memories": self._read_recent_cameo_memories(
                user_dir / "cameo_memory.jsonl",
                limit=12,
            ),
        }

    def save_adventure_result(
        self,
        group_id: str,
        user_id: str,
        card: AdventureDiaryCard,
        new_level: int,
        new_level_exp: int = 0,
    ) -> None:
        user_dir = self.get_user_dir(group_id, user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        now = self._now_ms()

        state_path = user_dir / "state.json"
        state = self._read_json(state_path)
        state.update(
            {
                "schema_version": state.get("schema_version", 1),
                "group_id": str(group_id),
                "user_id": str(user_id),
                "updated_at": now,
                "level": max(1, min(int(new_level), 100)),
                "level_exp": max(0, min(int(new_level_exp), 99)),
                "region": card.region,
                "location": card.location,
            }
        )
        state.setdefault("hp", 100)
        state.setdefault("mp", 100)
        state.setdefault("gold", 0)
        state.setdefault("inventory", [])
        state.setdefault("skills", {})
        state.setdefault("quests", [])
        state.setdefault("flags", {})
        teammate_gold_patches = self._apply_state_patches(state, card.update_patches)
        card.state_snapshot = self._to_jsonable(state)
        self._atomic_write_json(state_path, state)
        self._write_player_index(
            group_id=group_id,
            user_id=user_id,
            target_name=card.target_name,
            region=state.get("region") or card.region,
            location=state.get("location") or card.location,
            updated_at=now,
        )

        # 应用队友金币补丁
        if teammate_gold_patches:
            self._apply_teammate_gold_patches(group_id, teammate_gold_patches)

        # 应用队友等级经验（纯代码，AI 无需输出）
        level_exp_delta = self._extract_level_exp_delta(card.update_patches)
        if level_exp_delta > 0:
            mentioned_names = self._find_mentioned_teammate_names(group_id, card)
            if mentioned_names:
                self._apply_teammate_level_exp(
                    group_id,
                    max(1, min(int(new_level), 100)),
                    level_exp_delta,
                    mentioned_names,
                )

        self.append_log(
            group_id,
            user_id,
            {
                "type": "adventure_diary",
                "created_at": now,
                "title": card.title,
                "date_label": card.date_label,
                "action": card.action,
                "region": card.region,
                "location": card.location,
                "diary": card.diary,
                "encounter": card.encounter,
                "level_change": card.level_change,
                "level_exp": card.level_exp_after,
                "result": card.result,
                "changes": card.changes,
                "update_patches": card.update_patches,
            },
        )

    def maybe_compress_adventure_logs(
        self,
        group_id: str,
        user_id: str,
        *,
        interval: int,
        compress_count: int,
        summary_text: str,
    ) -> bool:
        if interval <= 0 or compress_count <= 0 or compress_count >= interval:
            return False
        text = str(summary_text or "").strip()
        if not text:
            return False

        user_dir = self.get_user_dir(group_id, user_id)
        log_path = user_dir / "adventure_log.jsonl"
        if not log_path.exists():
            return False

        try:
            raw_lines = log_path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            logger.warning(f"读取冒险日志失败，跳过压缩: {log_path} {exc}")
            return False

        parsed: list[dict[str, Any] | None] = []
        normal_adventures: list[tuple[int, dict[str, Any]]] = []
        adventure_ordinal = 0
        for index, line in enumerate(raw_lines):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                parsed.append(None)
                continue
            if not isinstance(item, dict):
                parsed.append(None)
                continue
            parsed.append(item)
            if item.get("type") == "adventure_summary":
                adventure_ordinal = max(
                    adventure_ordinal,
                    int(item.get("adventure_to", 0) or 0),
                )
                continue
            if item.get("type") == "adventure_diary":
                adventure_ordinal += 1
                normal_adventures.append((index, item))

        if len(normal_adventures) < interval:
            return False

        selected = normal_adventures[:compress_count]
        selected_indices = {index for index, _item in selected}
        first_ordinal = self._adventure_ordinal_for_log(raw_lines, selected[0][0])
        last_ordinal = self._adventure_ordinal_for_log(raw_lines, selected[-1][0])
        summary_record = {
            "type": "adventure_summary",
            "created_at": self._now_ms(),
            "title": f"第 {first_ordinal}-{last_ordinal} 次冒险",
            "date_label": f"第 {first_ordinal}-{last_ordinal} 次冒险",
            "adventure_from": first_ordinal,
            "adventure_to": last_ordinal,
            "compressed_count": len(selected),
            "result": text,
        }

        next_lines: list[str] = []
        inserted = False
        for index, line in enumerate(raw_lines):
            if index in selected_indices:
                if not inserted:
                    next_lines.append(json.dumps(summary_record, ensure_ascii=False))
                    inserted = True
                continue
            next_lines.append(line)

        tmp_path = log_path.with_suffix(log_path.suffix + ".tmp")
        output = "\n".join(next_lines)
        if output:
            output += "\n"
        tmp_path.write_text(output, encoding="utf-8")
        tmp_path.replace(log_path)
        return True

    def get_adventure_logs_for_compression(
        self,
        group_id: str,
        user_id: str,
        *,
        interval: int,
        compress_count: int,
    ) -> list[dict[str, Any]]:
        if interval <= 0 or compress_count <= 0 or compress_count >= interval:
            return []
        user_dir = self.get_user_dir(group_id, user_id)
        logs = self._read_recent_logs(user_dir / "adventure_log.jsonl", limit=0)
        normal_adventures = [
            item
            for item in logs
            if isinstance(item, dict) and item.get("type") == "adventure_diary"
        ]
        if len(normal_adventures) < interval:
            return []
        return normal_adventures[:compress_count]

    def append_log(self, group_id: str, user_id: str, record: dict[str, Any]) -> None:
        user_dir = self.get_user_dir(group_id, user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        log_path = user_dir / "adventure_log.jsonl"
        payload = dict(record)
        payload.setdefault("created_at", self._now_ms())
        with log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def append_cameo_memory(
        self,
        group_id: str,
        npc_user_id: str,
        record: dict[str, Any],
    ) -> None:
        user_dir = self.get_user_dir(group_id, npc_user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        log_path = user_dir / "cameo_memory.jsonl"
        payload = dict(record)
        payload["type"] = "cameo_memory"
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
                index = self._read_json(user_dir / "index.json")
                profile: dict[str, Any] = {}
                state: dict[str, Any] = {}
                if index:
                    target_name = index.get("target_name", "")
                    region = index.get("region", "")
                    location = index.get("location", "")
                    updated_at = int(index.get("updated_at", 0) or 0)
                else:
                    profile = self._read_json(user_dir / "profile.json")
                    state = self._read_json(user_dir / "state.json")
                    target_name = profile.get("card", {}).get("target_name", "")
                    region = state.get("region", "")
                    location = state.get("location", "")
                    updated_at = max(
                        int(profile.get("updated_at", 0) or 0),
                        int(state.get("updated_at", 0) or 0),
                    )
                saves.append(
                    {
                        "group_id": group_dir.name,
                        "user_id": user_dir.name,
                        "nickname": index.get("target_name", "") if index else profile.get("nickname", ""),
                        "target_name": target_name,
                        "race": profile.get("card", {}).get("race", ""),
                        "class_name": profile.get("card", {}).get("class_name", ""),
                        "level": state.get("level", 1),
                        "region": region,
                        "location": location,
                        "updated_at": updated_at,
                    }
                )
        return saves

    def list_saves_by_user(self, user_id: str) -> list[dict[str, Any]]:
        safe_user = self._safe_id(user_id)
        return [item for item in self.list_saves() if item.get("user_id") == safe_user]

    def find_birth_region_npcs(
        self,
        group_id: str,
        user_id: str,
        birth_region: str,
    ) -> list[dict[str, Any]]:
        region = str(birth_region or "").strip()
        if not region:
            return []

        current_user = self._safe_id(user_id)
        users_dir = self.root_dir / "groups" / self._safe_id(group_id) / "users"
        if not users_dir.exists():
            return []

        npcs: list[dict[str, Any]] = []
        for user_dir in sorted(p for p in users_dir.iterdir() if p.is_dir()):
            if user_dir.name == current_user:
                continue

            profile = self._read_json(user_dir / "profile.json")
            card = profile.get("card", {}) if isinstance(profile, dict) else {}
            if not isinstance(card, dict):
                continue
            if str(card.get("birth_region") or "").strip() != region:
                continue

            npc = self._build_npc_package(user_dir, profile=profile, source="same_birth_region")
            if npc:
                npcs.append(npc)
        return npcs

    def find_mentioned_npcs(
        self,
        group_id: str,
        user_id: str,
        action_text: str,
    ) -> list[dict[str, Any]]:
        text = str(action_text or "").strip()
        if not text:
            return []

        current_user = self._safe_id(user_id)
        users_dir = self.root_dir / "groups" / self._safe_id(group_id) / "users"
        if not users_dir.exists():
            return []

        npcs: list[dict[str, Any]] = []
        for user_dir in sorted(p for p in users_dir.iterdir() if p.is_dir()):
            if user_dir.name == current_user:
                continue

            index = self._read_json(user_dir / "index.json")
            target_name = str(index.get("target_name") or "").strip()
            if not target_name or target_name not in text:
                continue
            npc = self._build_npc_package(user_dir, source="mentioned_by_action")
            if npc:
                npcs.append(npc)
        return npcs

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
            "cameo_memories": self._read_recent_cameo_memories(
                user_dir / "cameo_memory.jsonl",
                limit=80,
            ),
        }

    def update_profile_card(
        self,
        group_id: str,
        user_id: str,
        updates: dict[str, Any],
    ) -> None:
        user_dir = self.get_user_dir(group_id, user_id)
        profile_path = user_dir / "profile.json"
        profile = self._read_json(profile_path)
        if not profile:
            raise ValueError("玩家 profile.json 不存在或无法读取")
        card = profile.get("card")
        if not isinstance(card, dict):
            card = {}
            profile["card"] = card

        string_fields = {
            "title",
            "subtitle",
            "target_name",
            "race",
            "class_name",
            "appearance",
            "personality",
            "talent",
            "birth_description",
            "birth_region",
            "birth_location",
            "quote",
            "footer",
        }
        for key in string_fields:
            if key in updates:
                card[key] = str(updates.get(key) or "").strip()

        if "likes" in updates:
            likes = updates.get("likes")
            if isinstance(likes, list):
                card["likes"] = [str(item).strip() for item in likes if str(item).strip()]

        if "stats" in updates:
            stats = updates.get("stats")
            if isinstance(stats, dict):
                card["stats"] = {
                    str(key).strip(): str(value).strip()
                    for key, value in stats.items()
                    if str(key).strip()
                }

        target_name = str(card.get("target_name") or "").strip()
        if target_name:
            profile["nickname"] = target_name
        profile["updated_at"] = self._now_ms()
        self._atomic_write_json(profile_path, profile)
        self.rebuild_player_index(group_id, user_id)

    def list_player_source_files(self, group_id: str, user_id: str) -> list[dict[str, Any]]:
        user_dir = self.get_user_dir(group_id, user_id)
        return [
            {
                "name": file_name,
                "exists": (user_dir / file_name).exists(),
                "kind": "jsonl" if file_name.endswith(".jsonl") else "json",
            }
            for file_name in sorted(self.SOURCE_FILE_NAMES)
        ]

    def read_player_source_file(
        self,
        group_id: str,
        user_id: str,
        file_name: str,
    ) -> str:
        path = self._player_source_path(group_id, user_id, file_name)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write_player_source_file(
        self,
        group_id: str,
        user_id: str,
        file_name: str,
        content: str,
    ) -> None:
        path = self._player_source_path(group_id, user_id, file_name)
        self._validate_source_content(file_name, content)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self._backup_source_file(path)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(str(content), encoding="utf-8")
        tmp_path.replace(path)
        if file_name in {"index.json", "profile.json", "state.json"}:
            self.rebuild_player_index(group_id, user_id)

    def rebuild_player_index(self, group_id: str, user_id: str) -> None:
        user_dir = self.get_user_dir(group_id, user_id)
        profile = self._read_json(user_dir / "profile.json")
        state = self._read_json(user_dir / "state.json")
        index = self._read_json(user_dir / "index.json")
        card = profile.get("card", {}) if isinstance(profile, dict) else {}
        target_name = (
            card.get("target_name")
            or profile.get("nickname")
            or index.get("target_name")
            or user_id
        )
        updated_at = max(
            int(profile.get("updated_at", 0) or 0),
            int(state.get("updated_at", 0) or 0),
            int(index.get("updated_at", 0) or 0),
            self._now_ms(),
        )
        self._write_player_index(
            group_id=group_id,
            user_id=user_id,
            target_name=target_name,
            region=state.get("region") or index.get("region", ""),
            location=state.get("location") or index.get("location", ""),
            updated_at=updated_at,
        )

    def delete_adventure_log(self, group_id: str, user_id: str, log_index: int) -> bool:
        user_dir = self.get_user_dir(group_id, user_id)
        log_path = user_dir / "adventure_log.jsonl"
        root = self.root_dir.resolve()
        target = log_path.resolve()
        if root != target and root not in target.parents:
            raise ValueError(f"非法日志路径: {target}")
        if not log_path.exists():
            return False

        lines = log_path.read_text(encoding="utf-8").splitlines()
        if log_index < 0 or log_index >= len(lines):
            return False

        del lines[log_index]
        tmp_path = log_path.with_suffix(log_path.suffix + ".tmp")
        text = "\n".join(lines)
        if text:
            text += "\n"
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(log_path)
        return True

    def delete_player_save(self, group_id: str, user_id: str) -> bool:
        user_dir = self.get_user_dir(group_id, user_id)
        root = self.root_dir.resolve()
        target = user_dir.resolve()
        if root != target and root not in target.parents:
            raise ValueError(f"非法存档路径: {target}")
        if not user_dir.exists():
            return False

        self.delete_cameo_memories_by_source(group_id, user_id)
        shutil.rmtree(user_dir)
        self._cleanup_empty_parent_dirs(user_dir)
        return True

    def delete_cameo_memories_by_source(self, group_id: str, source_user_id: str) -> int:
        source_user = self._safe_id(source_user_id)
        users_dir = self.root_dir / "groups" / self._safe_id(group_id) / "users"
        if not users_dir.exists():
            return 0

        removed_count = 0
        for user_dir in sorted(p for p in users_dir.iterdir() if p.is_dir()):
            log_path = user_dir / "cameo_memory.jsonl"
            if not log_path.exists():
                continue
            try:
                lines = log_path.read_text(encoding="utf-8").splitlines()
            except Exception as exc:
                logger.warning(f"读取客串记忆失败，跳过清理: {log_path} {exc}")
                continue

            kept_lines: list[str] = []
            changed = False
            for line in lines:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    kept_lines.append(line)
                    continue
                if (
                    isinstance(item, dict)
                    and item.get("type") == "cameo_memory"
                    and self._safe_id(item.get("source_user_id", "")) == source_user
                ):
                    removed_count += 1
                    changed = True
                    continue
                kept_lines.append(line)

            if not changed:
                continue
            tmp_path = log_path.with_suffix(log_path.suffix + ".tmp")
            text = "\n".join(kept_lines)
            if text:
                text += "\n"
            tmp_path.write_text(text, encoding="utf-8")
            tmp_path.replace(log_path)
        return removed_count

    def _cleanup_empty_parent_dirs(self, user_dir: Path) -> None:
        for path in [user_dir.parent, user_dir.parent.parent]:
            try:
                if path.exists() and path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
            except Exception:
                break

    def _touch_state_updated_at(self, state_path: Path, now: int) -> None:
        state = self._read_json(state_path)
        if not state:
            return
        state["updated_at"] = now
        self._atomic_write_json(state_path, state)

    def _write_player_index(
        self,
        *,
        group_id: str,
        user_id: str,
        target_name: object,
        region: object,
        location: object,
        updated_at: int,
    ) -> None:
        index = {
            "schema_version": 1,
            "group_id": str(group_id),
            "target_name": str(target_name or "").strip(),
            "region": str(region or "").strip(),
            "location": str(location or "").strip(),
            "updated_at": int(updated_at or self._now_ms()),
        }
        self._atomic_write_json(self.get_user_dir(group_id, user_id) / "index.json", index)

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
            all_lines = path.read_text(encoding="utf-8").splitlines()
            if limit and limit > 0:
                start_index = max(0, len(all_lines) - limit)
                lines = all_lines[start_index:]
            else:
                start_index = 0
                lines = all_lines
        except Exception as exc:
            logger.warning(f"读取冒险日志失败: {path} {exc}")
            return []

        logs: list[dict[str, Any]] = []
        for offset, line in enumerate(lines):
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    item["_log_index"] = start_index + offset
                    logs.append(item)
            except json.JSONDecodeError:
                continue
        return logs

    def _adventure_ordinal_for_log(self, raw_lines: list[str], target_index: int) -> int:
        ordinal = 0
        for index, line in enumerate(raw_lines):
            if index > target_index:
                break
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "adventure_summary":
                ordinal = max(ordinal, int(item.get("adventure_to", 0) or 0))
            elif item.get("type") == "adventure_diary":
                ordinal += 1
        return max(1, ordinal)

    def _read_last_adventure_summary(self, path: Path) -> dict[str, Any]:
        for item in reversed(self._read_recent_logs(path, limit=80)):
            if item.get("type") != "adventure_diary":
                continue
            return {
                "encounter": item.get("encounter", ""),
                "result": item.get("result", ""),
                "region": item.get("region", ""),
                "location": item.get("location", ""),
                "created_at": item.get("created_at", 0),
            }
        return {}

    def _read_recent_cameo_memories(self, path: Path, limit: int = 5) -> list[dict[str, Any]]:
        memories = [
            {
                "created_at": item.get("created_at", 0),
                "source_target_name": item.get("source_target_name", ""),
                "encounter": item.get("encounter", ""),
                "result": item.get("result", ""),
                "region": item.get("region", ""),
                "location": item.get("location", ""),
                "title": item.get("title", ""),
                "_log_index": item.get("_log_index"),
            }
            for item in self._read_recent_logs(path, limit=max(limit * 4, limit))
            if item.get("type") == "cameo_memory"
        ]
        return memories[-limit:]

    def delete_cameo_memory(self, group_id: str, user_id: str, log_index: int) -> bool:
        user_dir = self.get_user_dir(group_id, user_id)
        log_path = user_dir / "cameo_memory.jsonl"
        root = self.root_dir.resolve()
        target = log_path.resolve()
        if root != target and root not in target.parents:
            raise ValueError(f"非法快照路径: {target}")
        if not log_path.exists():
            return False

        lines = log_path.read_text(encoding="utf-8").splitlines()
        if log_index < 0 or log_index >= len(lines):
            return False

        del lines[log_index]
        tmp_path = log_path.with_suffix(log_path.suffix + ".tmp")
        text = "\n".join(lines)
        if text:
            text += "\n"
        tmp_path.write_text(text, encoding="utf-8")
        tmp_path.replace(log_path)
        return True

    def _build_npc_package(
        self,
        user_dir: Path,
        *,
        profile: dict[str, Any] | None = None,
        source: str,
    ) -> dict[str, Any] | None:
        profile = profile if isinstance(profile, dict) else self._read_json(user_dir / "profile.json")
        card = profile.get("card", {}) if isinstance(profile, dict) else {}
        if not isinstance(card, dict):
            return None
        target_name = str(
            card.get("target_name") or profile.get("nickname") or user_dir.name
        ).strip()
        state = self._replace_protagonist_key(
            self._read_json(user_dir / "state.json"),
            target_name,
        )
        return {
            "_user_id": user_dir.name,
            "_source": source,
            "target_name": target_name,
            "race": card.get("race", ""),
            "class_name": card.get("class_name", ""),
            "appearance": card.get("appearance", ""),
            "personality": card.get("personality", ""),
            "talent": card.get("talent", ""),
            "birth_region": card.get("birth_region", ""),
            "birth_location": card.get("birth_location", ""),
            "stats": card.get("stats", {}),
            "likes": card.get("likes", []),
            "state": state,
            "last_adventure": self._read_last_adventure_summary(
                user_dir / "adventure_log.jsonl"
            ),
            "cameo_memories": self._read_recent_cameo_memories(
                user_dir / "cameo_memory.jsonl",
                limit=5,
            ),
        }

    def _replace_protagonist_key(self, value: Any, target_name: str) -> Any:
        if isinstance(value, dict):
            replaced: dict[str, Any] = {}
            for key, child in value.items():
                next_key = target_name if key == "主角" else key
                replaced[next_key] = self._replace_protagonist_key(child, target_name)
            return replaced
        if isinstance(value, list):
            return [self._replace_protagonist_key(item, target_name) for item in value]
        return value

    def _player_source_path(self, group_id: str, user_id: str, file_name: str) -> Path:
        if file_name not in self.SOURCE_FILE_NAMES:
            raise ValueError(f"不允许编辑这个存档文件: {file_name}")
        user_dir = self.get_user_dir(group_id, user_id)
        root = user_dir.resolve()
        target = (user_dir / file_name).resolve()
        if root != target and root not in target.parents:
            raise ValueError(f"非法存档源码路径: {target}")
        return target

    @staticmethod
    def _validate_source_content(file_name: str, content: str) -> None:
        text = str(content)
        if file_name.endswith(".json"):
            data = json.loads(text or "{}")
            if not isinstance(data, dict):
                raise ValueError(f"{file_name} 必须是 JSON 对象")
            return
        if file_name.endswith(".jsonl"):
            for line_no, line in enumerate(text.splitlines(), start=1):
                if not line.strip():
                    continue
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError(f"{file_name} 第 {line_no} 行必须是 JSON 对象")
            return
        raise ValueError(f"不支持的存档源码类型: {file_name}")

    @staticmethod
    def _backup_source_file(path: Path) -> None:
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = path.with_name(f"{path.name}.{timestamp}.bak")
            shutil.copy2(path, backup_path)
        except Exception as exc:
            logger.warning(f"备份存档源码失败: {path} {exc}")

    GOLD_PATHS = {"/金币", "/主角/金币", "/gold", "/主角/gold"}

    @staticmethod
    def _is_teammate_gold_path(path: str) -> str | None:
        """判断路径是否为队友金币路径，返回队友名或 None。"""
        path = str(path or "").strip()
        if not path.startswith("/"):
            return None
        parts = path.split("/")
        # /队友名/金币 或 /队友名/gold
        if len(parts) == 3 and parts[2] in ("金币", "gold"):
            name = parts[1].strip()
            if name and name != "主角":
                return name
        return None

    def _apply_state_patches(
        self,
        state: dict[str, Any],
        patches: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """应用状态补丁到 state，返回队友金币补丁 {队友名: [{op, value}, ...]}。"""
        teammate_gold_patches: dict[str, list[dict[str, Any]]] = {}
        if not isinstance(patches, list):
            return teammate_gold_patches
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            op = str(patch.get("op") or "").strip()
            path = str(patch.get("path") or "").strip()
            if not path.startswith("/") or path in {"/region", "/location"}:
                continue
            if path in {"/level/经验", "/等级/经验", "/主角/等级/经验"}:
                continue
            if path in self.GOLD_PATHS:
                self._apply_gold_patch(state, op, patch.get("value"))
                continue
            # 检测队友金币路径
            teammate_name = self._is_teammate_gold_path(path)
            if teammate_name:
                if op in {"+", "-"}:
                    teammate_gold_patches.setdefault(teammate_name, []).append(
                        {"op": op, "value": patch.get("value")}
                    )
                continue
            parts = self._split_patch_path(path)
            if not parts:
                continue
            if op == "+":
                self._apply_add_patch(state, parts, patch.get("value"))
            elif op == "-":
                self._apply_sub_patch(state, parts, patch.get("value"))
            elif op in {"replace", "insert"}:
                self._set_nested_value(state, parts, patch.get("value"))
        return teammate_gold_patches

    def _apply_gold_patch(
        self,
        state: dict[str, Any],
        op: str,
        value: object,
    ) -> None:
        delta = self._number_value(value)
        current = self._number_value(state.get("gold", 0))
        if op == "+":
            state["gold"] = max(0, current + delta)
        elif op == "-":
            state["gold"] = max(0, current - delta)

    def _apply_teammate_gold_patches(
        self,
        group_id: str,
        teammate_gold_patches: dict[str, list[dict[str, Any]]],
    ) -> None:
        """将队友金币补丁应用到对应队友的存档中。"""
        users_dir = self.root_dir / "groups" / self._safe_id(group_id) / "users"
        if not users_dir.exists():
            return

        for teammate_name, patches in teammate_gold_patches.items():
            if not teammate_name or not patches:
                continue
            # 通过玩家索引查找队友
            target_user_dir = self._find_user_dir_by_target_name(users_dir, teammate_name)
            if not target_user_dir:
                logger.debug(f"未找到队友 {teammate_name} 的存档，跳过金币补丁")
                continue
            state_path = target_user_dir / "state.json"
            if not state_path.exists():
                continue
            state = self._read_json(state_path)
            if not isinstance(state, dict):
                continue
            state.setdefault("gold", 0)
            for patch in patches:
                self._apply_gold_patch(state, patch.get("op"), patch.get("value"))
            state["updated_at"] = self._now_ms()
            self._atomic_write_json(state_path, state)
            logger.info(f"已应用队友 {teammate_name} 的金币补丁: {patches}")

    LEVEL_EXP_PATHS = {"/level/经验", "/等级/经验", "/主角/等级/经验"}

    def _extract_level_exp_delta(self, patches: list[dict[str, Any]]) -> int:
        """从补丁列表中提取主角获得的等级经验增量总和。"""
        if not isinstance(patches, list):
            return 0
        delta = 0
        for patch in patches:
            if not isinstance(patch, dict):
                continue
            op = str(patch.get("op") or "").strip()
            path = str(patch.get("path") or "").strip()
            if op == "+" and path in self.LEVEL_EXP_PATHS:
                delta += self._number_value(patch.get("value"))
        return delta

    def _apply_teammate_level_exp(
        self,
        group_id: str,
        main_level: int,
        level_exp_delta: int,
        teammate_names: set[str],
    ) -> None:
        """根据主角等级经验，按等级差为队友分配调整后的经验。

        队友比主角低 n 级：经验 × (n + 1)
        队友比主角高 n 级：经验 ÷ (n + 1)
        """
        users_dir = self.root_dir / "groups" / self._safe_id(group_id) / "users"
        if not users_dir.exists():
            return

        for name in teammate_names:
            if not name:
                continue
            target_user_dir = self._find_user_dir_by_target_name(users_dir, name)
            if not target_user_dir:
                logger.debug(f"未找到队友 {name} 的存档，跳过等级经验")
                continue
            state_path = target_user_dir / "state.json"
            if not state_path.exists():
                continue
            state = self._read_json(state_path)
            if not isinstance(state, dict):
                continue

            teammate_level = max(1, min(int(state.get("level", 1) or 1), 100))
            level_diff = main_level - teammate_level

            if level_diff > 0:
                adjusted = level_exp_delta * (level_diff + 1)
            elif level_diff < 0:
                adjusted = int(level_exp_delta / (abs(level_diff) + 1))
            else:
                adjusted = level_exp_delta

            if adjusted <= 0:
                continue

            current_exp = max(0, min(int(state.get("level_exp", 0) or 0), 99))
            new_exp = current_exp + adjusted
            level = teammate_level

            while new_exp >= 100 and level < 100:
                level += 1
                new_exp -= 100

            if level >= 100:
                level = 100
                new_exp = 0

            state["level"] = level
            state["level_exp"] = max(0, min(new_exp, 99))
            state["updated_at"] = self._now_ms()
            self._atomic_write_json(state_path, state)
            logger.info(
                f"已应用队友 {name} 的等级经验: "
                f"base={level_exp_delta}, adjusted={adjusted}, "
                f"Lv.{teammate_level}->Lv.{level}"
            )

    def _find_mentioned_teammate_names(
        self,
        group_id: str,
        card: AdventureDiaryCard,
    ) -> set[str]:
        """从 encounter、result、changes 中找出被提及的同群队友名字。"""
        text_parts = [
            str(card.encounter or ""),
            str(card.result or ""),
        ]
        if isinstance(card.changes, list):
            text_parts.extend(str(c) for c in card.changes)
        mention_text = "\n".join(text_parts)
        if not mention_text.strip():
            return set()

        users_dir = self.root_dir / "groups" / self._safe_id(group_id) / "users"
        if not users_dir.exists():
            return set()

        protagonist = str(card.target_name or "").strip()
        matched: set[str] = set()
        for user_dir in sorted(p for p in users_dir.iterdir() if p.is_dir()):
            index = self._read_json(user_dir / "index.json")
            if not isinstance(index, dict):
                continue
            name = str(index.get("target_name") or "").strip()
            if not name or name == protagonist:
                continue
            if name in mention_text:
                matched.add(name)
        return matched

    def _find_user_dir_by_target_name(
        self,
        users_dir: Path,
        target_name: str,
    ) -> Path | None:
        """在用户目录中通过 target_name 查找对应的用户目录。"""
        if not users_dir.exists():
            return None
        for user_dir in sorted(p for p in users_dir.iterdir() if p.is_dir()):
            index = self._read_json(user_dir / "index.json")
            if isinstance(index, dict):
                name = str(index.get("target_name") or "").strip()
                if name == target_name:
                    return user_dir
        return None

    def _apply_add_patch(
        self,
        state: dict[str, Any],
        parts: list[str],
        value: object,
    ) -> None:
        delta = self._number_value(value)
        parent = self._ensure_nested_parent(state, parts)
        key = parts[-1]
        current = self._number_value(parent.get(key, 0))
        next_value = current + delta
        if key in PROGRESS_KEYS:
            self._ensure_progress_level(parent)
            next_value = self._normalize_progress_value(parent, next_value)
        parent[key] = next_value

    def _apply_sub_patch(
        self,
        state: dict[str, Any],
        parts: list[str],
        value: object,
    ) -> None:
        delta = self._number_value(value)
        parent = self._ensure_nested_parent(state, parts)
        key = parts[-1]
        current = self._number_value(parent.get(key, 0))
        next_value = current - delta
        if key in PROGRESS_KEYS:
            self._ensure_progress_level(parent)
            next_value = self._normalize_progress_value(parent, next_value)
        parent[key] = max(0, next_value)

    def _set_nested_value(
        self,
        state: dict[str, Any],
        parts: list[str],
        value: object,
    ) -> None:
        parent = self._ensure_nested_parent(state, parts)
        key = parts[-1]
        if isinstance(parent.get(key), list) and not isinstance(value, list):
            parent[key].append(value)
            return
        parent[key] = value
        if key in PROGRESS_KEYS:
            self._ensure_progress_level(parent)
            parent[key] = self._normalize_progress_value(parent, self._number_value(value))

    @staticmethod
    def _ensure_progress_level(parent: dict[str, Any]) -> None:
        for level_key in ("等级", "level", "Lv", "lv"):
            if level_key in parent:
                try:
                    parent[level_key] = max(1, int(float(parent.get(level_key) or 1)))
                except Exception:
                    parent[level_key] = 1
                if level_key != "等级":
                    parent["等级"] = parent[level_key]
                    parent.pop(level_key, None)
                return
        parent["等级"] = 1

    @staticmethod
    def _normalize_progress_value(parent: dict[str, Any], value: int | float) -> int | float:
        next_value = max(0, value)
        while next_value >= 100:
            parent["等级"] = max(1, int(PlayerSaveRepository._number_value(parent.get("等级", 1)))) + 1
            next_value -= 100
        return max(0, min(next_value, 99))

    def _ensure_nested_parent(
        self,
        root: dict[str, Any],
        parts: list[str],
    ) -> dict[str, Any]:
        current = root
        for part in parts[:-1]:
            child = current.get(part)
            if not isinstance(child, dict):
                child = {}
                current[part] = child
            current = child
        return current

    @staticmethod
    def _split_patch_path(path: str) -> list[str]:
        return [
            part.replace("~1", "/").replace("~0", "~")
            for part in path.split("/")[1:]
            if part
        ]

    @staticmethod
    def _number_value(value: object) -> int | float:
        try:
            number = float(value or 0)
        except Exception:
            return 0
        return int(number) if number.is_integer() else number

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
