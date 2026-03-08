"""Shared fixtures for TidyUp tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tidyup.config import Config


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    """Config with all paths pointing to tmp_path."""
    downloads = tmp_path / "Downloads"
    data = tmp_path / "data"

    downloads.mkdir()
    data.mkdir()

    config = Config(
        target_dir=downloads,
        data_dir=data,
    )
    config.ensure_dirs()
    return config


@pytest.fixture
def sample_downloads(tmp_config: Config) -> Config:
    """Config with a set of sample files in Downloads, including nested dirs."""
    dl = tmp_config.target_dir

    # Root-level files
    (dl / "installer.dmg").write_bytes(b"\x00" * 100)
    (dl / "setup.pkg").write_bytes(b"\x00" * 100)
    (dl / "tax-return-2025.pdf").write_bytes(b"%PDF-fake content")
    (dl / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    (dl / "notes.txt").write_text("Meeting notes from Friday")
    (dl / "report.docx").write_bytes(b"PK\x03\x04" + b"\x00" * 100)

    # Nested structure
    projects = dl / "Projects"
    projects.mkdir()
    (projects / "readme.md").write_text("# My Project")

    deep = projects / "2024"
    deep.mkdir()
    (deep / "data.csv").write_text("a,b,c\n1,2,3")

    # Hidden dir (should be skipped)
    hidden = dl / ".hidden_dir"
    hidden.mkdir()
    (hidden / "secret.txt").write_text("hidden")

    # Hidden file (should be skipped)
    (dl / ".DS_Store").write_bytes(b"\x00")

    return tmp_config


@pytest.fixture
def mock_ollama_response():
    """Factory for mock Ollama responses in new organize format."""

    def _make(files_data: list[dict]) -> dict:
        return {"files": files_data}

    return _make
