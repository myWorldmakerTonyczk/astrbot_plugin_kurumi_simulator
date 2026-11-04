"""Load bundled market defaults independently of runtime/user settings."""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "market.json"
with CONFIG_PATH.open(encoding="utf-8") as stream:
    _config = json.load(stream)

for _section in ("default_urls", "labels", "endpoints"):
    if not isinstance(_config.get(_section), dict) or not all(
        isinstance(key, str) and isinstance(value, str) and value.strip()
        for key, value in _config[_section].items()
    ):
        raise ValueError(f"行情配置 {_section} 必须是非空字符串键值表：{CONFIG_PATH}")

DEFAULT_URLS = _config["default_urls"]
LABELS = _config["labels"]
ENDPOINTS = _config["endpoints"]
