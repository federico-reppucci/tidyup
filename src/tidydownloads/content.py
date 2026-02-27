"""Content preview extraction using macOS-native tools + poppler."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

log = logging.getLogger("tidydownloads")

TIMEOUT = 5  # seconds for subprocess calls
MAX_CHARS = 500

TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml",
    ".py", ".js", ".ts", ".html", ".css", ".sh", ".bash",
    ".rb", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".hpp",
    ".toml", ".ini", ".cfg", ".conf", ".log", ".sql",
    ".m", ".swift", ".r", ".tex",
}

# Extensions that textutil can convert to plain text
TEXTUTIL_EXTENSIONS = {".doc", ".docx", ".rtf", ".ppt", ".xls", ".xlsx"}

# Metadata keys to extract with mdls
_MDLS_KEYS = [
    "kMDItemTitle",
    "kMDItemContentType",
    "kMDItemCreator",
    "kMDItemContentCreationDate",
    "kMDItemPixelWidth",
    "kMDItemPixelHeight",
]


def extract_preview(path: Path, max_chars: int = MAX_CHARS) -> str:
    """Extract a text preview from a file. Returns empty string on failure."""
    ext = path.suffix.lower()

    try:
        if ext == ".pdf":
            return _extract_pdf(path, max_chars)
        if ext in TEXTUTIL_EXTENSIONS:
            return _extract_textutil(path, max_chars)
        if ext in TEXT_EXTENSIONS:
            return _extract_text(path, max_chars)
    except Exception as e:
        log.debug("Content extraction failed for %s: %s", path.name, e)

    # Universal fallback: Spotlight metadata for any file type
    try:
        meta = extract_metadata(path, max_chars)
        if meta:
            return meta
    except Exception as e:
        log.debug("Metadata extraction failed for %s: %s", path.name, e)

    return ""


def extract_metadata(path: Path, max_chars: int = MAX_CHARS) -> str:
    """Extract Spotlight metadata via mdls as a content hint.

    Works for images, archives, binary files — anything macOS has indexed.
    """
    try:
        args = ["mdls"]
        for key in _MDLS_KEYS:
            args.extend(["-name", key])
        args.append(str(path))

        result = subprocess.run(
            args, capture_output=True, text=True, timeout=TIMEOUT,
        )
        if result.returncode == 0:
            lines = [
                line.strip() for line in result.stdout.splitlines()
                if "(null)" not in line and "=" in line
            ]
            return "\n".join(lines)[:max_chars]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return ""


def _extract_pdf(path: Path, max_chars: int) -> str:
    """Extract text from PDF via pdftotext, fallback to mdls."""
    try:
        result = subprocess.run(
            ["pdftotext", str(path), "-"],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout[:max_chars].strip()
    except FileNotFoundError:
        log.debug("pdftotext not installed, falling back to mdls")
    except subprocess.TimeoutExpired:
        log.debug("pdftotext timed out for %s", path.name)

    # Fallback: Spotlight metadata
    return extract_metadata(path, max_chars)


def _extract_textutil(path: Path, max_chars: int) -> str:
    """Extract text from Word/RTF/PPT/XLS via textutil."""
    try:
        result = subprocess.run(
            ["textutil", "-stdout", "-convert", "txt", str(path)],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout[:max_chars].strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # Fallback to metadata if textutil fails
    return extract_metadata(path, max_chars)


def _extract_text(path: Path, max_chars: int) -> str:
    """Read plain text files directly."""
    try:
        return path.read_text(errors="replace")[:max_chars].strip()
    except OSError:
        return ""
