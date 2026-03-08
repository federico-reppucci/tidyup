"""Configuration with sensible defaults and optional JSON override."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Config"]


@dataclass
class Config:
    target_dir: Path = field(default_factory=lambda: Path.home() / "Downloads")
    data_dir: Path = field(default_factory=lambda: Path.home() / ".local" / "share" / "tidyup")
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:4b"
    excluded: list[str] = field(default_factory=lambda: [".DS_Store", ".localized", "*.tmp"])
    excluded_dirs: list[str] = field(default_factory=lambda: [".Trash", ".Spotlight-V100"])
    parallel_requests: int = 4
    mini_batch_size: int = 5

    @property
    def undo_log_path(self) -> Path:
        return self.data_dir / "undo_log.jsonl"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls) -> Config:
        config = cls()
        config_path = Path.home() / ".config" / "tidyup" / "config.json"
        if config_path.exists():
            overrides = json.loads(config_path.read_text())
            for key, value in overrides.items():
                if hasattr(config, key):
                    current = getattr(config, key)
                    if isinstance(current, Path):
                        setattr(config, key, Path(value).expanduser())
                    else:
                        setattr(config, key, value)
        config.ensure_dirs()
        return config
