"""Tests for classifier module."""

from unittest.mock import MagicMock

from tidydownloads.classifier import (
    OllamaBackend,
    ParallelOllamaBackend,
    RulesOnlyBackend,
    classify_files,
    classify_tier1,
)
from tidydownloads.helpers import validate_destination
from tidydownloads.scanner import FileInfo, scan_downloads
from tidydownloads.taxonomy import FolderInfo, Taxonomy


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
    """Test confidence threshold at 0.45 (new default)."""
    mock_client = MagicMock()
    mock_client.generate.return_value = {
        "files": [
            {
                "file": "tax-return-2025.pdf",
                "action": "move",
                "destination": "02 Finance",
                "reason": "tax doc",
                "confidence": 0.9,
            },
            {
                "file": "screenshot.png",
                "action": "delete",
                "reason": "screenshot",
                "confidence": 0.3,
            },
            {
                "file": "notes.txt",
                "action": "move",
                "destination": "03 Work",
                "reason": "notes",
                "confidence": 0.5,
            },
            {
                "file": "report.docx",
                "action": "move",
                "destination": "03 Work/Reports",
                "reason": "report",
                "confidence": 0.8,
            },
        ]
    }

    backend = OllamaBackend(mock_client)
    files = scan_downloads(sample_downloads)
    taxonomy = Taxonomy()

    results = classify_files(files, taxonomy, sample_downloads, backend=backend)

    by_name = {r.filename: r for r in results}

    # Tier 1 should catch these
    assert by_name["installer.dmg"].action == "delete"
    assert by_name["setup.pkg"].action == "delete"

    # LLM with high confidence (above 0.45)
    assert by_name["tax-return-2025.pdf"].action == "move"
    assert by_name["report.docx"].action == "move"

    # notes.txt has confidence 0.5 — above new threshold 0.45 → move
    assert by_name["notes.txt"].action == "move"

    # screenshot.png has confidence 0.3 — below 0.45, but action is "delete"
    # which is exempt from threshold (only "move" actions get filtered)
    # Actually the delete action at 0.3 → below threshold → unsorted
    assert by_name["screenshot.png"].action == "unsorted"


# --- Destination validation tests ---


def test_validate_destination_exact_match():
    taxonomy = Taxonomy(
        folders=[
            FolderInfo("02 Finance", subfolders=["Investments", "Mortgage"]),
            FolderInfo("03 Work", subfolders=["Reports"]),
        ]
    )
    assert validate_destination("02 Finance/Investments", taxonomy) == "02 Finance/Investments"


def test_validate_destination_case_insensitive():
    taxonomy = Taxonomy(folders=[FolderInfo("02 Finance", subfolders=["Investments"])])
    assert validate_destination("02 finance/investments", taxonomy) == "02 Finance/Investments"


def test_validate_destination_stripped_prefix():
    taxonomy = Taxonomy(folders=[FolderInfo("04 Education", subfolders=["MBA"])])
    assert validate_destination("Education/MBA", taxonomy) == "04 Education/MBA"


def test_validate_destination_top_folder_only():
    taxonomy = Taxonomy(folders=[FolderInfo("01 Personal ID & Documents")])
    assert validate_destination("Personal ID & Documents", taxonomy) == "01 Personal ID & Documents"


def test_validate_destination_no_match():
    taxonomy = Taxonomy(folders=[FolderInfo("02 Finance")])
    assert validate_destination("Nonexistent", taxonomy) == "Nonexistent"


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


# --- Parallel backend tests ---


def test_parallel_backend_classifies_files():
    """ParallelOllamaBackend splits files into mini-batches and classifies them."""
    mock_client = MagicMock()
    mock_client.generate.return_value = {
        "files": [
            {
                "file": "report.pdf",
                "action": "move",
                "destination": "03 Work/Reports",
                "reason": "report",
                "confidence": 0.85,
            },
            {
                "file": "notes.txt",
                "action": "move",
                "destination": "03 Work",
                "reason": "notes",
                "confidence": 0.7,
            },
        ]
    }

    backend = ParallelOllamaBackend(mock_client, mini_batch=2, workers=2)
    files = [_make_file("report.pdf", ".pdf"), _make_file("notes.txt", ".txt")]
    taxonomy = Taxonomy()

    from tidydownloads.config import Config

    config = Config()

    results = backend.classify(files, taxonomy, config)
    assert len(results) == 2
    assert mock_client.generate.call_count == 1  # 2 files, batch_size=2 → 1 batch


def test_parallel_backend_multiple_batches():
    """ParallelOllamaBackend creates multiple batches when files exceed mini_batch."""
    call_count = 0

    def fake_generate(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        # Return matching files based on what's in the prompt
        files_result = []
        for name in ["a.pdf", "b.pdf", "c.pdf", "d.pdf", "e.pdf"]:
            if name in prompt:
                files_result.append(
                    {
                        "file": name,
                        "action": "move",
                        "destination": "03 Work",
                        "reason": "work file",
                        "confidence": 0.8,
                    }
                )
        return {"files": files_result}

    mock_client = MagicMock()
    mock_client.generate.side_effect = fake_generate

    backend = ParallelOllamaBackend(mock_client, mini_batch=2, workers=2)
    files = [_make_file(f"{c}.pdf", ".pdf") for c in "abcde"]
    taxonomy = Taxonomy()

    from tidydownloads.config import Config

    config = Config()

    results = backend.classify(files, taxonomy, config)
    assert len(results) == 5
    assert call_count == 3  # 5 files / 2 per batch = 3 batches


def test_parallel_backend_handles_batch_error():
    """A failed batch yields 'unsorted' results without losing other batches."""
    call_count = 0

    def fake_generate(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("simulated LLM error")
        files_result = []
        for name in ["a.pdf", "b.pdf", "c.pdf", "d.pdf"]:
            if name in prompt:
                files_result.append(
                    {
                        "file": name,
                        "action": "move",
                        "destination": "03 Work",
                        "reason": "work",
                        "confidence": 0.8,
                    }
                )
        return {"files": files_result}

    mock_client = MagicMock()
    mock_client.generate.side_effect = fake_generate

    backend = ParallelOllamaBackend(mock_client, mini_batch=2, workers=1)
    files = [_make_file(f"{c}.pdf", ".pdf") for c in "abcd"]
    taxonomy = Taxonomy()

    from tidydownloads.config import Config

    config = Config()

    results = backend.classify(files, taxonomy, config)
    assert len(results) == 4

    # One batch failed → 2 unsorted, one batch succeeded → 2 move
    actions = [r.action for r in results]
    assert actions.count("unsorted") == 2
    assert actions.count("move") == 2


def test_parallel_backend_passes_options_to_generate():
    """ParallelOllamaBackend passes num_predict, num_ctx, top_k, and keep_alive."""
    mock_client = MagicMock()
    mock_client.generate.return_value = {
        "files": [
            {
                "file": "doc.pdf",
                "action": "move",
                "destination": "03 Work",
                "reason": "work",
                "confidence": 0.9,
            },
        ]
    }

    backend = ParallelOllamaBackend(mock_client, mini_batch=5, workers=1)
    files = [_make_file("doc.pdf", ".pdf")]
    taxonomy = Taxonomy()

    from tidydownloads.config import Config

    config = Config()

    backend.classify(files, taxonomy, config)

    _, kwargs = mock_client.generate.call_args
    assert kwargs["keep_alive"] == "10m"
    assert kwargs["options"]["num_ctx"] == 4096
    assert kwargs["options"]["top_k"] == 20
    # num_predict = 1 file * 60 + 50 = 110
    assert kwargs["options"]["num_predict"] == 110


def test_parallel_backend_validates_destinations():
    """ParallelOllamaBackend validates destinations against taxonomy."""
    mock_client = MagicMock()
    mock_client.generate.return_value = {
        "files": [
            {
                "file": "thesis.pdf",
                "action": "move",
                "destination": "Education/MBA",
                "reason": "edu doc",
                "confidence": 0.9,
            },
        ]
    }

    backend = ParallelOllamaBackend(mock_client, mini_batch=5, workers=1)
    files = [_make_file("thesis.pdf", ".pdf")]
    taxonomy = Taxonomy(folders=[FolderInfo("04 Education", subfolders=["MBA"])])

    from tidydownloads.config import Config

    config = Config()

    results = backend.classify(files, taxonomy, config)
    assert len(results) == 1
    assert results[0].destination == "04 Education/MBA"
