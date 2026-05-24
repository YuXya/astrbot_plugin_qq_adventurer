from __future__ import annotations


class ConfigManager:
    def __init__(self, config):
        self.config = config

    def _get_group(self, name: str) -> dict:
        try:
            value = self.config.get(name, {})
        except AttributeError:
            value = getattr(self.config, name, {})
        return value if isinstance(value, dict) else {}

    def get_llm_provider_id(self) -> str:
        return str(self._get_group("llm").get("llm_provider_id", "")).strip()

    def get_llm_retries(self) -> int:
        return int(self._get_group("llm").get("llm_retries", 2) or 2)

    def get_llm_backoff(self) -> int:
        return int(self._get_group("llm").get("llm_backoff", 2) or 2)

    def get_default_theme(self) -> str:
        return str(
            self._get_group("adventure").get("default_theme", "森林入口")
        ).strip()

    def get_max_choices(self) -> int:
        return int(self._get_group("adventure").get("max_choices", 3) or 3)

    def get_debug_mode(self) -> bool:
        return bool(self._get_group("adventure").get("debug_mode", False))

    def get_use_mock_data(self) -> bool:
        return bool(self._get_group("adventure").get("use_mock_data", False))

    def get_t2i_rendering_strategies(self) -> list[dict]:
        group = self._get_group("t2i_rendering")
        return [
            {
                "full_page": True,
                "type": group.get("t2i_r1_type", "png"),
                "quality": group.get("t2i_r1_quality", 100),
                "device_scale_factor_level": group.get(
                    "t2i_r1_device_scale", "ultra"
                ),
                "timeout": group.get("t2i_r1_timeout", 50000),
            },
            {
                "full_page": True,
                "type": group.get("t2i_r2_type", "jpeg"),
                "quality": group.get("t2i_r2_quality", 80),
                "device_scale_factor_level": group.get("t2i_r2_device_scale", "high"),
                "timeout": group.get("t2i_r2_timeout", 100000),
            },
        ]

    def get_t2i_max_concurrent(self) -> int:
        return int(self._get_group("performance").get("max_concurrent_t2i", 1) or 1)

