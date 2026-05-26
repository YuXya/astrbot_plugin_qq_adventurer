from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from astrbot.api.star import StarTools

from ...utils.logger import logger
from . import defaults


class EditableResourceManager:
    PROMPT_FILES = {
        "reincarnation_prompt": "prompts/reincarnation_prompt.txt",
        "adventure_diary_prompt": "prompts/adventure_diary_prompt.txt",
        "persona_reinforcement": "prompts/persona_reinforcement.txt",
        "default_system_prompt": "prompts/default_system_prompt.txt",
        "world_book_wrapper": "prompts/world_book_wrapper.txt",
        "world_book_empty": "prompts/world_book_empty.txt",
    }

    def __init__(self, plugin_name: str = "astrbot_plugin_qq_adventurer"):
        self.root_dir = StarTools.get_data_dir(plugin_name) / "editable"
        self.backup_dir = self.root_dir / "backups"
        self._ensure_defaults()

    @property
    def world_book_path(self) -> Path:
        return self.root_dir / "world_book" / "default.json"

    def get_prompt(self, name: str) -> str:
        relative = self.PROMPT_FILES[name]
        return self.read_text(relative)

    def render_prompt(self, name: str, variables: dict[str, object]) -> str:
        text = self.get_prompt(name)
        return self.render_text(text, variables)

    @staticmethod
    def render_text(text: str, variables: dict[str, object]) -> str:
        rendered = str(text)
        for key, value in variables.items():
            rendered = rendered.replace("{{" + key + "}}", str(value))
        return rendered

    def read_text(self, relative_path: str) -> str:
        path = self._resolve(relative_path)
        try:
            return path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"读取可编辑资源失败: {path} {exc}")
            return ""

    def write_text(self, relative_path: str, content: str) -> None:
        path = self._resolve(relative_path)
        if path.exists():
            self._backup(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")

    def write_world_book(self, content: str) -> None:
        json.loads(content)
        self.write_text("world_book/default.json", content)

    def list_editable_files(self) -> list[dict[str, str]]:
        files = [
            {
                "id": "world_book/default.json",
                "label": "世界书 default.json",
                "type": "json",
            }
        ]
        files.extend(
            {
                "id": relative,
                "label": label,
                "type": "text",
            }
            for label, relative in [
                ("转生卡 Prompt", self.PROMPT_FILES["reincarnation_prompt"]),
                ("冒险日记 Prompt", self.PROMPT_FILES["adventure_diary_prompt"]),
                ("人格格式优先级 Prompt", self.PROMPT_FILES["persona_reinforcement"]),
                ("默认 System Prompt", self.PROMPT_FILES["default_system_prompt"]),
                ("世界书包装话术", self.PROMPT_FILES["world_book_wrapper"]),
                ("世界书未命中话术", self.PROMPT_FILES["world_book_empty"]),
            ]
        )
        return files

    def _ensure_defaults(self) -> None:
        defaults_map = {
            "world_book/default.json": defaults.load_builtin_world_book(),
            self.PROMPT_FILES["reincarnation_prompt"]: defaults.REINCARNATION_PROMPT,
            self.PROMPT_FILES["adventure_diary_prompt"]: defaults.ADVENTURE_DIARY_PROMPT,
            self.PROMPT_FILES["persona_reinforcement"]: defaults.PERSONA_REINFORCEMENT_PROMPT,
            self.PROMPT_FILES["default_system_prompt"]: defaults.DEFAULT_SYSTEM_PROMPT,
            self.PROMPT_FILES["world_book_wrapper"]: defaults.WORLD_BOOK_WRAPPER,
            self.PROMPT_FILES["world_book_empty"]: defaults.WORLD_BOOK_EMPTY,
        }
        for relative, content in defaults_map.items():
            path = self._resolve(relative)
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

    def _resolve(self, relative_path: str) -> Path:
        path = (self.root_dir / relative_path).resolve()
        root = self.root_dir.resolve()
        if root != path and root not in path.parents:
            raise ValueError(f"非法资源路径: {relative_path}")
        return path

    def _backup(self, path: Path) -> None:
        try:
            relative = path.relative_to(self.root_dir)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / relative.parent / f"{path.name}.{timestamp}.bak"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)
        except Exception as exc:
            logger.warning(f"备份可编辑资源失败: {path} {exc}")
