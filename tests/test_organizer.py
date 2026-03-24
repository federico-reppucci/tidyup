"""Tests for organizer module."""

import os
from pathlib import Path
from unittest.mock import MagicMock

from tidyup.helpers import NOT_CLASSIFIED_REASON, parse_organize_response
from tidyup.ollama_client import GenerateResult, OllamaError
from tidyup.organizer import OllamaOrganizer, ParallelOllamaOrganizer, detect_duplicates
from tidyup.scanner import FileInfo


def _gen_result(data: dict) -> GenerateResult:
    return GenerateResult(data=data, token_count=10, elapsed=1.0)


def _make_file(
    rel_path: str,
    size: int = 100,
    mime: str = "application/octet-stream",
    mtime: float = 0,
    path: Path | None = None,
) -> FileInfo:
    name = Path(rel_path).name
    ext = Path(rel_path).suffix.lower()
    return FileInfo(
        name=name,
        path=path or Path(f"/fake/{rel_path}"),
        relative_path=rel_path,
        extension=ext,
        size=size,
        modified_time=mtime,
        mime_type=mime,
    )


# --- parse_organize_response tests ---


def test_parse_response_basic():
    files = [_make_file("report.pdf"), _make_file("notes.txt")]
    response = {
        "files": [
            {"file": "report.pdf", "folder": "Work/Reports", "reason": "work report"},
            {"file": "notes.txt", "folder": "Work", "reason": "work notes"},
        ]
    }
    results = parse_organize_response(response, files)
    assert len(results) == 2
    by_path = {r.relative_path: r for r in results}
    assert by_path["report.pdf"].destination_folder == "Work/Reports"
    assert by_path["report.pdf"].needs_move is True
    assert by_path["notes.txt"].destination_folder == "Work"
    assert by_path["notes.txt"].needs_move is True


def test_parse_response_file_already_correct():
    """File already in the right folder -> needs_move=False."""
    files = [_make_file("Work/report.pdf")]
    response = {
        "files": [
            {"file": "Work/report.pdf", "folder": "Work", "reason": "already correct"},
        ]
    }
    results = parse_organize_response(response, files)
    assert len(results) == 1
    assert results[0].needs_move is False


def test_parse_response_root_file_stays():
    """Root file with empty folder -> needs_move=False."""
    files = [_make_file("readme.txt")]
    response = {
        "files": [
            {"file": "readme.txt", "folder": "", "reason": "root file"},
        ]
    }
    results = parse_organize_response(response, files)
    assert len(results) == 1
    assert results[0].needs_move is False


def test_parse_response_missing_files():
    """Files not in LLM response stay in place."""
    files = [_make_file("a.pdf"), _make_file("b.pdf")]
    response = {
        "files": [
            {"file": "a.pdf", "folder": "Work", "reason": "work"},
        ]
    }
    results = parse_organize_response(response, files)
    assert len(results) == 2
    by_path = {r.relative_path: r for r in results}
    assert by_path["b.pdf"].needs_move is False
    assert by_path["b.pdf"].reason == NOT_CLASSIFIED_REASON


def test_parse_response_empty():
    """Empty response -> all files stay."""
    files = [_make_file("a.pdf")]
    response = {"files": []}
    results = parse_organize_response(response, files)
    assert len(results) == 1
    assert results[0].needs_move is False


def test_parse_response_malformed():
    """Non-list files field -> all stay."""
    files = [_make_file("a.pdf")]
    response = {"files": "invalid"}
    results = parse_organize_response(response, files)
    assert len(results) == 1
    assert results[0].needs_move is False


def test_parse_response_ignores_unknown_files():
    """Files not in our list are ignored."""
    files = [_make_file("a.pdf")]
    response = {
        "files": [
            {"file": "a.pdf", "folder": "Work", "reason": "work"},
            {"file": "unknown.pdf", "folder": "Other", "reason": "unknown"},
        ]
    }
    results = parse_organize_response(response, files)
    assert len(results) == 1


# --- Duplicate detection tests ---


def test_detect_duplicates_finds_identical_files(tmp_path):
    f1 = tmp_path / "original.txt"
    f2 = tmp_path / "copy.txt"
    f1.write_text("same content")
    f2.write_text("same content")
    os.utime(f1, (1000, 1000))
    os.utime(f2, (2000, 2000))

    files = [
        _make_file("original.txt", size=f1.stat().st_size, mtime=1000.0, path=f1),
        _make_file("copy.txt", size=f2.stat().st_size, mtime=2000.0, path=f2),
    ]

    trash, unique = detect_duplicates(files)
    assert len(trash) == 1
    assert trash[0].relative_path == "copy.txt"
    assert trash[0].destination_folder == "Trash"
    assert "Duplicate" in trash[0].reason
    assert len(unique) == 1


def test_detect_duplicates_different_content(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("aaaa")
    f2.write_text("bbbb")

    files = [
        _make_file("a.txt", size=f1.stat().st_size, mtime=1000.0, path=f1),
        _make_file("b.txt", size=f2.stat().st_size, mtime=2000.0, path=f2),
    ]

    trash, unique = detect_duplicates(files)
    assert len(trash) == 0
    assert len(unique) == 2


def test_detect_duplicates_different_sizes(tmp_path):
    f1 = tmp_path / "short.txt"
    f2 = tmp_path / "long.txt"
    f1.write_text("hi")
    f2.write_text("hello world")

    files = [
        _make_file("short.txt", size=f1.stat().st_size, mtime=1000.0, path=f1),
        _make_file("long.txt", size=f2.stat().st_size, mtime=2000.0, path=f2),
    ]

    trash, unique = detect_duplicates(files)
    assert len(trash) == 0
    assert len(unique) == 2


def test_detect_duplicates_three_copies(tmp_path):
    for name, mtime in [("a.txt", 3000), ("b.txt", 1000), ("c.txt", 2000)]:
        p = tmp_path / name
        p.write_text("same")
        os.utime(p, (mtime, mtime))

    size = (tmp_path / "a.txt").stat().st_size
    files = [
        _make_file("a.txt", size=size, mtime=3000.0, path=tmp_path / "a.txt"),
        _make_file("b.txt", size=size, mtime=1000.0, path=tmp_path / "b.txt"),
        _make_file("c.txt", size=size, mtime=2000.0, path=tmp_path / "c.txt"),
    ]

    trash, unique = detect_duplicates(files)
    assert len(trash) == 2
    dup_paths = {d.relative_path for d in trash}
    assert dup_paths == {"a.txt", "c.txt"}
    assert len(unique) == 1
    assert unique[0].relative_path == "b.txt"


def test_detect_duplicates_skips_directories(tmp_path):
    app_dir = tmp_path / "SomeApp.app"
    app_dir.mkdir()

    files = [
        _make_file("SomeApp.app", size=4096, mtime=1000.0, path=app_dir),
    ]

    trash, unique = detect_duplicates(files)
    assert len(trash) == 0
    assert len(unique) == 1


# --- OllamaOrganizer tests ---


def test_organizer_parses_response():
    mock_client = MagicMock()
    mock_client.generate.return_value = _gen_result(
        {
            "files": [
                {"file": "report.pdf", "folder": "Work/Reports", "reason": "work report"},
            ]
        }
    )

    org = OllamaOrganizer(mock_client)
    files = [_make_file("report.pdf", mime="application/pdf")]
    results = org.organize(files)

    assert len(results) == 1
    assert results[0].destination_folder == "Work/Reports"
    assert results[0].needs_move is True


def test_organizer_handles_empty_files():
    mock_client = MagicMock()
    org = OllamaOrganizer(mock_client)
    results = org.organize([])
    assert results == []
    mock_client.generate.assert_not_called()


def test_organizer_handles_missing_files_in_response():
    mock_client = MagicMock()
    # Both initial and retry return empty -> file stays unclassified
    mock_client.generate.return_value = _gen_result({"files": []})

    org = OllamaOrganizer(mock_client)
    files = [_make_file("unknown.pdf")]
    results = org.organize(files)

    assert len(results) == 1
    assert results[0].needs_move is False
    assert results[0].reason == NOT_CLASSIFIED_REASON
    # Should have been called twice: initial + retry
    assert mock_client.generate.call_count == 2


# --- ParallelOllamaOrganizer tests ---


def test_parallel_organizer_small_count_uses_single():
    """Under 80 files, parallel organizer delegates to single OllamaOrganizer."""
    mock_client = MagicMock()
    mock_client.generate.return_value = _gen_result(
        {
            "files": [
                {"file": "a.pdf", "folder": "Work", "reason": "work"},
            ]
        }
    )

    org = ParallelOllamaOrganizer(mock_client, batch_size=40, workers=2)
    files = [_make_file("a.pdf")]
    results = org.organize(files)

    assert len(results) == 1
    assert mock_client.generate.call_count == 1


def test_parallel_organizer_handles_batch_error():
    """A failed batch yields in-place results without losing other batches."""
    call_count = 0

    def fake_generate(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("simulated LLM error")
        files_result = []
        for i in range(100):
            name = f"file{i:03d}.pdf"
            if name in prompt:
                files_result.append({"file": name, "folder": "Work", "reason": "work"})
        return _gen_result({"files": files_result})

    mock_client = MagicMock()
    mock_client.generate.side_effect = fake_generate

    org = ParallelOllamaOrganizer(mock_client, batch_size=40, workers=1)
    files = [_make_file(f"file{i:03d}.pdf") for i in range(100)]
    results = org.organize(files)

    # All 100 files should have results (some from successful batches, some from error)
    assert len(results) == 100


# --- Retry logic tests ---


def test_organizer_retries_unclassified_files():
    """LLM misses a file on first call, classifies it on retry."""
    call_count = 0

    def fake_generate(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: only classify a.pdf, miss b.pdf
            return _gen_result({"files": [{"file": "a.pdf", "folder": "Work", "reason": "work"}]})
        else:
            # Retry: classify b.pdf
            return _gen_result({"files": [{"file": "b.pdf", "folder": "Media", "reason": "image"}]})

    mock_client = MagicMock()
    mock_client.generate.side_effect = fake_generate

    org = OllamaOrganizer(mock_client)
    files = [_make_file("a.pdf"), _make_file("b.pdf")]
    results = org.organize(files)

    assert len(results) == 2
    by_path = {r.relative_path: r for r in results}
    assert by_path["a.pdf"].destination_folder == "Work"
    assert by_path["b.pdf"].destination_folder == "Media"
    assert by_path["b.pdf"].reason != NOT_CLASSIFIED_REASON
    assert call_count == 2


def test_organizer_no_retry_when_all_classified():
    """No retry when all files are classified on first call."""
    mock_client = MagicMock()
    mock_client.generate.return_value = _gen_result(
        {
            "files": [
                {"file": "a.pdf", "folder": "Work", "reason": "work"},
                {"file": "b.pdf", "folder": "Media", "reason": "image"},
            ]
        }
    )

    org = OllamaOrganizer(mock_client)
    files = [_make_file("a.pdf"), _make_file("b.pdf")]
    results = org.organize(files)

    assert len(results) == 2
    # Only 1 LLM call — no retry needed
    assert mock_client.generate.call_count == 1


def test_organizer_retry_still_unclassified():
    """Both initial and retry miss the file -> stays unclassified."""
    mock_client = MagicMock()
    mock_client.generate.return_value = _gen_result(
        {"files": [{"file": "a.pdf", "folder": "Work", "reason": "work"}]}
    )

    org = OllamaOrganizer(mock_client)
    files = [_make_file("a.pdf"), _make_file("b.pdf")]
    results = org.organize(files)

    assert len(results) == 2
    by_path = {r.relative_path: r for r in results}
    assert by_path["b.pdf"].reason == NOT_CLASSIFIED_REASON
    assert by_path["b.pdf"].needs_move is False
    assert mock_client.generate.call_count == 2


def test_organizer_retry_error_preserves_unclassified():
    """Retry LLM call fails -> original unclassified proposals preserved, no crash."""
    call_count = 0

    def fake_generate(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _gen_result({"files": [{"file": "a.pdf", "folder": "Work", "reason": "work"}]})
        else:
            raise OllamaError("connection timeout")

    mock_client = MagicMock()
    mock_client.generate.side_effect = fake_generate

    org = OllamaOrganizer(mock_client)
    files = [_make_file("a.pdf"), _make_file("b.pdf")]
    results = org.organize(files)

    assert len(results) == 2
    by_path = {r.relative_path: r for r in results}
    assert by_path["a.pdf"].destination_folder == "Work"
    assert by_path["b.pdf"].reason == NOT_CLASSIFIED_REASON
    assert by_path["b.pdf"].needs_move is False
    assert call_count == 2


# --- LLM error retry tests ---


def test_organizer_retries_on_llm_error():
    """Single organizer retries once on LLM error before giving up."""
    call_count = 0

    def fake_generate(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OllamaError("malformed JSON")
        return _gen_result({"files": [{"file": "a.pdf", "folder": "Work", "reason": "work"}]})

    mock_client = MagicMock()
    mock_client.generate.side_effect = fake_generate

    org = OllamaOrganizer(mock_client)
    files = [_make_file("a.pdf")]
    results = org.organize(files)

    assert len(results) == 1
    assert results[0].destination_folder == "Work"
    assert results[0].needs_move is True
    # First call fails, retry succeeds
    assert call_count == 2


def test_organizer_retry_both_fail_returns_error_proposals():
    """Both initial and retry LLM calls fail -> returns error proposals."""
    mock_client = MagicMock()
    mock_client.generate.side_effect = OllamaError("persistent error")

    org = OllamaOrganizer(mock_client)
    files = [_make_file("a.pdf"), _make_file("b.pdf")]
    results = org.organize(files)

    assert len(results) == 2
    for r in results:
        assert r.needs_move is False
        assert "LLM error" in r.reason
    # Initial + retry = 2 calls
    assert mock_client.generate.call_count == 2


def test_parallel_organizer_retries_failed_batch():
    """Parallel organizer retries a failed batch once before propagating error."""
    call_count = 0

    def fake_generate(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        # First call for second batch fails, retry succeeds
        if call_count == 2:
            raise OllamaError("temporary failure")
        files_result = []
        for i in range(100):
            name = f"file{i:03d}.pdf"
            if name in prompt:
                files_result.append({"file": name, "folder": "Work", "reason": "work"})
        return _gen_result({"files": files_result})

    mock_client = MagicMock()
    mock_client.generate.side_effect = fake_generate

    org = ParallelOllamaOrganizer(mock_client, batch_size=40, workers=1)
    files = [_make_file(f"file{i:03d}.pdf") for i in range(100)]
    results = org.organize(files)

    assert len(results) == 100
    # All files should be classified (retry succeeded)
    classified = [r for r in results if r.destination_folder == "Work"]
    assert len(classified) == 100
