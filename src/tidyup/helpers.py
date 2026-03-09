"""Shared helpers: data types, previews, and LLM response parsing."""

from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tidyup.content import extract_preview
from tidyup.scanner import FileInfo

NOT_CLASSIFIED_REASON = "Not classified by LLM"

__all__ = [
    "NOT_CLASSIFIED_REASON",
    "PREVIEW_CHARS",
    "Proposal",
    "build_file_descriptions",
    "current_parent",
    "parse_organize_response",
    "precompute_previews",
    "sha256_file",
]

log = logging.getLogger("tidyup")

PREVIEW_CHARS = 150


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Proposal:
    relative_path: str  # current location (e.g. "Projects/report.pdf")
    destination_folder: str  # proposed folder (e.g. "Work/Reports"), "" for root
    reason: str
    needs_move: bool  # computed: current parent != destination_folder


def _is_useful_preview(preview: str) -> bool:
    """Filter out Spotlight metadata noise — only keep actual content previews."""
    return bool(preview) and "kMDItem" not in preview


def build_file_descriptions(
    files: list[FileInfo],
    previews: dict[str, str],
) -> list[str]:
    """Build file description strings for the LLM prompt, keyed by relative_path."""
    descriptions = []
    for f in files:
        desc = f"{f.relative_path} ({f.mime_type}, {f.size_human})"
        preview = previews.get(f.relative_path, "")
        if _is_useful_preview(preview):
            preview_short = preview[:PREVIEW_CHARS].replace("\n", " ")
            desc += f" -- content preview: {preview_short}"
        descriptions.append(desc)
    return descriptions


def precompute_previews(files: list[FileInfo], max_workers: int = 4) -> dict[str, str]:
    """Extract content previews in parallel, keyed by relative_path."""
    previews: dict[str, str] = {}

    def _extract(f: FileInfo) -> tuple[str, str]:
        return f.relative_path, extract_preview(f.path)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for rel_path, preview in pool.map(_extract, files):
            if preview:
                previews[rel_path] = preview

    return previews


def current_parent(relative_path: str) -> str:
    """Get the parent folder of a relative path, or '' for root files."""
    parent = str(PurePosixPath(relative_path).parent)
    return "" if parent == "." else parent


def parse_organize_response(
    response: dict,
    files: list[FileInfo],
) -> list[Proposal]:
    """Parse LLM JSON response into Proposal objects.

    Expected format: {"files": [{"file": "<relative_path>", "folder": "<dest>", "reason": "..."}]}
    Computes needs_move by comparing current parent to proposed folder.
    """
    results: list[Proposal] = []
    file_set = {f.relative_path for f in files}

    items = response.get("files", [])
    if not isinstance(items, list):
        log.warning("LLM returned non-list 'files' field")
        # All files stay in place on malformed response
        return [
            Proposal(
                relative_path=f.relative_path,
                destination_folder=current_parent(f.relative_path),
                reason="LLM returned invalid format",
                needs_move=False,
            )
            for f in files
        ]

    seen: set[str] = set()
    for item in items:
        file_path = item.get("file", "")
        if file_path not in file_set or file_path in seen:
            continue
        seen.add(file_path)

        folder = item.get("folder", "")
        if not isinstance(folder, str):
            folder = ""
        folder = folder.strip().rstrip("/")

        reason = item.get("reason", "")
        current = current_parent(file_path)
        needs_move = current != folder

        results.append(
            Proposal(
                relative_path=file_path,
                destination_folder=folder,
                reason=reason,
                needs_move=needs_move,
            )
        )

    # Files not in LLM response stay in place
    for f in files:
        if f.relative_path not in seen:
            results.append(
                Proposal(
                    relative_path=f.relative_path,
                    destination_folder=current_parent(f.relative_path),
                    reason=NOT_CLASSIFIED_REASON,
                    needs_move=False,
                )
            )

    return results
