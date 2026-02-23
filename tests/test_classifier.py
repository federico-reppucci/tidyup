"""Tests for classifier module."""

from unittest.mock import MagicMock

from tidydownloads.classifier import (
    Classification,
    OllamaBackend,
    RulesOnlyBackend,
    classify_files,
    classify_tier1,
)
from tidydownloads.scanner import FileInfo, scan_downloads
from tidydownloads.taxonomy import Taxonomy


def _make_file(name, ext=None, size=100, mime="application/octet-stream"):
    from pathlib import Path
    ext = ext or ("." + name.rsplit(".", 1)[-1] if "." in name else "")
    return FileInfo(
        name=name,
        path=Path(f"/fake/{name}"),
        extension=ext,
        size=size,
        modified_time=0,
        mime_type=mime,
    )


# --- Tier 1 tests ---

def test_tier1_dmg():
    result = classify_tier1(_make_file("installer.dmg", ".dmg"))
    assert result is not None
    assert result.action == "delete"
    assert result.confidence >= 0.9


def test_tier1_pkg():
    result = classify_tier1(_make_file("setup.pkg", ".pkg"))
    assert result is not None
    assert result.action == "delete"


def test_tier1_crdownload():
    result = classify_tier1(_make_file("file.crdownload", ".crdownload"))
    assert result is not None
    assert result.action == "delete"


def test_tier1_unknown_extension():
    result = classify_tier1(_make_file("document.pdf", ".pdf"))
    assert result is None


def test_tier1_torrent():
    result = classify_tier1(_make_file("movie.torrent", ".torrent"))
    assert result is not None
    assert result.action == "delete"


# --- Tier 2 / Ollama backend tests ---

def test_ollama_backend_parses_response():
    mock_client = MagicMock()
    mock_client.generate.return_value = {
        "files": [
            {
                "file": "report.pdf",
                "action": "move",
                "destination": "03 Work/Reports",
                "reason": "Looks like a work report",
                "confidence": 0.85,
            }
        ]
    }

    backend = OllamaBackend(mock_client)
    files = [_make_file("report.pdf", ".pdf")]
    taxonomy = Taxonomy()

    from tidydownloads.config import Config
    config = Config()

    results = backend.classify(files, taxonomy, config)
    assert len(results) == 1
    assert results[0].action == "move"
    assert results[0].destination == "03 Work/Reports"
    assert results[0].confidence == 0.85


def test_ollama_backend_handles_missing_files():
    mock_client = MagicMock()
    mock_client.generate.return_value = {"files": []}

    backend = OllamaBackend(mock_client)
    files = [_make_file("unknown.pdf", ".pdf")]
    taxonomy = Taxonomy()

    from tidydownloads.config import Config
    config = Config()

    results = backend.classify(files, taxonomy, config)
    assert len(results) == 1
    assert results[0].action == "skip"


# --- Confidence filter tests ---

def test_confidence_filter(sample_downloads):
    mock_client = MagicMock()
    mock_client.generate.return_value = {
        "files": [
            {"file": "tax-return-2025.pdf", "action": "move",
             "destination": "02 Finance", "reason": "tax doc", "confidence": 0.9},
            {"file": "screenshot.png", "action": "delete",
             "reason": "screenshot", "confidence": 0.3},
            {"file": "notes.txt", "action": "move",
             "destination": "03 Work", "reason": "notes", "confidence": 0.5},
            {"file": "report.docx", "action": "move",
             "destination": "03 Work/Reports", "reason": "report", "confidence": 0.8},
        ]
    }

    backend = OllamaBackend(mock_client)
    files = scan_downloads(sample_downloads)
    taxonomy = Taxonomy()

    results = classify_files(files, taxonomy, sample_downloads, backend=backend)

    # Check that low confidence files are skipped
    by_name = {r.filename: r for r in results}

    # Tier 1 should catch these
    assert by_name["installer.dmg"].action == "delete"
    assert by_name["setup.pkg"].action == "delete"

    # LLM with high confidence
    assert by_name["tax-return-2025.pdf"].action == "move"
    assert by_name["report.docx"].action == "move"

    # LLM with low confidence → skipped
    assert by_name["screenshot.png"].action == "skip"
    assert by_name["notes.txt"].action == "skip"


# --- Rules-only backend ---

def test_rules_only_backend():
    backend = RulesOnlyBackend()
    files = [
        _make_file("installer.dmg", ".dmg"),
        _make_file("report.pdf", ".pdf"),
    ]

    from tidydownloads.config import Config
    config = Config()

    results = backend.classify(files, Taxonomy(), config)
    assert len(results) == 2
    assert results[0].action == "delete"
    assert results[1].action == "skip"


# --- Adversarial inputs ---

def test_adversarial_filename_with_dots():
    """File with dots in name should still classify by extension."""
    result = classify_tier1(_make_file("file...dmg", ".dmg"))
    assert result is not None
    assert result.action == "delete"


def test_empty_extension():
    result = classify_tier1(_make_file("Makefile", ""))
    assert result is None
