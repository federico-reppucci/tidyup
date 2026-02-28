"""Shared fixtures for TidyDownloads tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tidydownloads.config import Config


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    """Config with all paths pointing to tmp_path."""
    downloads = tmp_path / "Downloads"
    documents = tmp_path / "Documents"
    data = tmp_path / "data"

    downloads.mkdir()
    documents.mkdir()
    data.mkdir()

    config = Config(
        downloads_dir=downloads,
        documents_dir=documents,
        data_dir=data,
    )
    config.ensure_dirs()
    return config


@pytest.fixture
def sample_downloads(tmp_config: Config) -> Config:
    """Config with a set of sample files in Downloads."""
    dl = tmp_config.downloads_dir

    # Tier 1: obvious deletes
    (dl / "installer.dmg").write_bytes(b"\x00" * 100)
    (dl / "setup.pkg").write_bytes(b"\x00" * 100)
    (dl / "partial.crdownload").write_bytes(b"\x00" * 50)

    # Ambiguous files for Tier 2
    (dl / "tax-return-2025.pdf").write_bytes(b"%PDF-fake content")
    (dl / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    (dl / "notes.txt").write_text("Meeting notes from Friday")
    (dl / "report.docx").write_bytes(b"PK\x03\x04" + b"\x00" * 100)

    # Hidden file (should be skipped)
    (dl / ".DS_Store").write_bytes(b"\x00")

    # Directory (should be skipped)
    (dl / "some_folder").mkdir()

    return tmp_config


@pytest.fixture
def sample_documents(tmp_config: Config) -> Config:
    """Config with a sample Documents structure."""
    docs = tmp_config.documents_dir

    finance = docs / "02 Finance"
    finance.mkdir()
    (finance / "Investments").mkdir()
    (finance / "Investments" / "statement-2025.pdf").write_bytes(b"pdf")
    (finance / "Mortgage").mkdir()

    work = docs / "03 Work"
    work.mkdir()
    (work / "Reports").mkdir()
    (work / "Reports" / "quarterly-report.pdf").write_bytes(b"pdf")

    personal = docs / "01 Personal"
    personal.mkdir()

    return tmp_config


@pytest.fixture
def mock_ollama_response():
    """Factory for mock Ollama responses."""

    def _make(files_data: list[dict]) -> dict:
        return {"files": files_data}

    return _make
