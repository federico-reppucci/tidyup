"""Shared classification helpers: data types, validation, previews, and LLM response parsing."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from tidydownloads.content import extract_preview
from tidydownloads.scanner import FileInfo
from tidydownloads.taxonomy import Taxonomy

__all__ = [
    "PREVIEW_CHARS",
    "Classification",
    "build_file_descriptions",
    "parse_llm_response",
    "precompute_previews",
    "validate_destination",
]

log = logging.getLogger("tidydownloads")

PREVIEW_CHARS = 150


@dataclass
class Classification:
    filename: str
    action: str  # "move" | "delete" | "unsorted" | "skip"
    destination: str  # Documents subfolder path (only for "move")
    reason: str
    confidence: float
    method: str  # "rule" | "llm"


def validate_destination(destination: str, taxonomy: Taxonomy) -> str:
    """Fuzzy-match LLM output against valid taxonomy paths.

    Match hierarchy: exact → case-insensitive → stripped numeric prefix → top-folder.
    Returns the best matching valid path, or the original if no match found.
    """
    if not destination:
        return destination

    valid_paths = taxonomy.valid_paths()
    dest_clean = destination.strip().rstrip("/")

    # 1. Exact match
    for path in valid_paths:
        if path == dest_clean:
            return path

    # 2. Case-insensitive match
    dest_lower = dest_clean.lower()
    for path in valid_paths:
        if path.lower() == dest_lower:
            return path

    # 3. Match ignoring numeric prefix (e.g. "Education/MBA" → "04 Education/MBA")
    def strip_prefix(s: str) -> str:
        parts = s.split("/")
        return "/".join(p.lstrip("0123456789 ") for p in parts).lower()

    dest_stripped = strip_prefix(dest_clean)
    for path in valid_paths:
        if strip_prefix(path) == dest_stripped:
            return path

    # 4. Top-folder only match — if LLM gave just the top folder name, resolve it
    dest_top = dest_clean.split("/")[0].lower()
    dest_top_stripped = dest_top.lstrip("0123456789 ")
    for folder in taxonomy.folders:
        folder_lower = folder.name.lower()
        folder_stripped = folder.name.lstrip("0123456789 ").lower()
        if folder_lower == dest_top or folder_stripped == dest_top_stripped:
            # If the LLM also gave a subfolder, try to match it
            parts = dest_clean.split("/", 1)
            if len(parts) > 1:
                sub_name = parts[1].lower()
                for sub in folder.subfolders:
                    if sub.lower() == sub_name:
                        return f"{folder.name}/{sub}"
            return folder.name

    return dest_clean


def build_file_descriptions(
    files: list[FileInfo],
    previews: dict[str, str],
) -> list[str]:
    """Build file description strings for the LLM prompt."""
    descriptions = []
    for f in files:
        desc = f"{f.name} ({f.mime_type}, {f.size_human})"
        preview = previews.get(f.name, "")
        if preview:
            preview_short = preview[:PREVIEW_CHARS].replace("\n", " ")
            desc += f" — content preview: {preview_short}"
        descriptions.append(desc)
    return descriptions


def precompute_previews(files: list[FileInfo], max_workers: int = 4) -> dict[str, str]:
    """Extract content previews in parallel."""
    previews: dict[str, str] = {}

    def _extract(f: FileInfo) -> tuple[str, str]:
        return f.name, extract_preview(f.path)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for name, preview in pool.map(_extract, files):
            if preview:
                previews[name] = preview

    return previews


def parse_llm_response(
    response: dict,
    batch: list[FileInfo],
) -> list[Classification]:
    """Parse LLM JSON response into Classification objects."""
    results: list[Classification] = []
    batch_names = {f.name for f in batch}

    items = response.get("files", [])
    if not isinstance(items, list):
        log.warning("LLM returned non-list 'files' field")
        return [
            Classification(f.name, "skip", "", "LLM returned invalid format", 0.0, "llm")
            for f in batch
        ]

    seen: set[str] = set()
    for item in items:
        filename = item.get("file", "")
        if filename not in batch_names or filename in seen:
            continue
        seen.add(filename)

        action = item.get("action", "")
        if action not in ("move", "delete"):
            action = "skip"

        destination = item.get("destination", "") if action == "move" else ""
        reason = item.get("reason", "")
        try:
            confidence = float(item.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        results.append(
            Classification(
                filename=filename,
                action=action,
                destination=destination,
                reason=reason,
                confidence=confidence,
                method="llm",
            )
        )

    # Any files not in the response get skipped
    for f in batch:
        if f.name not in seen:
            results.append(
                Classification(
                    filename=f.name,
                    action="skip",
                    destination="",
                    reason="Not classified by LLM",
                    confidence=0.0,
                    method="llm",
                )
            )

    return results
