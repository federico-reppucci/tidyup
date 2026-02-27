"""Discover Documents folder structure with sample filenames for LLM context."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("tidydownloads")

MAX_SAMPLES = 5


@dataclass
class FolderInfo:
    name: str
    subfolders: list[str] = field(default_factory=list)
    sample_files: list[str] = field(default_factory=list)


SUBFOLDER_THRESHOLD = 3  # show subfolders only for folders with more than this many


@dataclass
class Taxonomy:
    folders: list[FolderInfo] = field(default_factory=list)
    _subfolder_samples: dict[str, list[str]] = field(default_factory=dict)

    def find_folder(self, name: str) -> FolderInfo | None:
        """Find a folder by name, tolerating numeric prefixes and case differences.

        Matches "Education" to "04 Education", "work" to "Work", etc.
        """
        name_lower = name.lower().strip()
        # Exact match first
        for f in self.folders:
            if f.name.lower() == name_lower:
                return f
        # Strip numeric prefix (e.g., "04 Education" → "education")
        for f in self.folders:
            stripped = f.name.lstrip("0123456789 ").lower()
            if stripped == name_lower:
                return f
        # Prefix match (e.g., "Education" matches "04 Education")
        for f in self.folders:
            if name_lower in f.name.lower():
                return f
        return None

    def valid_paths(self) -> list[str]:
        """Return all valid destination paths (top-level and subfolder)."""
        paths: list[str] = []
        for folder in self.folders:
            paths.append(folder.name)
            for sub in folder.subfolders:
                paths.append(f"{folder.name}/{sub}")
        return paths

    def to_prompt_text(self) -> str:
        """Format taxonomy as text for the LLM prompt (full detail)."""
        lines: list[str] = []
        for folder in self.folders:
            lines.append(f"{folder.name}/")
            for sub in folder.subfolders:
                key = f"{folder.name}/{sub}"
                samples = self._subfolder_samples.get(key, [])
                if samples:
                    example = ", ".join(samples)
                    lines.append(f"  ├── {sub}/ (e.g., {example})")
                else:
                    lines.append(f"  ├── {sub}/")
            if folder.sample_files:
                example = ", ".join(folder.sample_files[:3])
                lines.append(f"  (root files: {example})")
        return "\n".join(lines)

    def to_compact_text(self) -> str:
        """Compact taxonomy: one line per folder with subfolder hints.

        Designed for small LLMs that can't reason over long context.
        Format: ``FolderName — sub1, sub2, sub3`` on a single line.
        Valid destination paths (folder/subfolder) are implicit from the
        listed names.
        """
        lines: list[str] = []
        for folder in self.folders:
            if folder.subfolders:
                desc = ", ".join(folder.subfolders[:5])
                if len(folder.subfolders) > 5:
                    desc += f", ... ({len(folder.subfolders)} total)"
                lines.append(f"{folder.name} — {desc}")
            else:
                lines.append(folder.name)
        return "\n".join(lines)

    def to_midsize_text(self, max_bytes: int = 3072) -> str:
        """Mid-size taxonomy: full paths with 1-2 sample filenames per subfolder.

        Shows exact destination paths the LLM should output, with sample files
        to disambiguate sibling subfolders. Target ~2KB.

        Format:
            04 Education/MBA — strategy-case-study.pdf, marketing-final.docx
            04 Education/Polimi — meccanica-razionale.pdf
            02 Finance/Investments — vanguard-statement.pdf
            01 Personal ID & Documents
        """
        lines: list[str] = []
        for folder in self.folders:
            if folder.subfolders:
                for sub in folder.subfolders:
                    key = f"{folder.name}/{sub}"
                    samples = self._subfolder_samples.get(key, [])[:2]
                    if samples:
                        lines.append(f"{key} — {', '.join(samples)}")
                    else:
                        lines.append(key)
            else:
                lines.append(folder.name)

        text = "\n".join(lines)
        # Trim if over budget: drop samples first, then subfolders
        if len(text.encode()) > max_bytes:
            lines = []
            for folder in self.folders:
                if folder.subfolders:
                    for sub in folder.subfolders:
                        lines.append(f"{folder.name}/{sub}")
                else:
                    lines.append(folder.name)
            text = "\n".join(lines)

        while len(text.encode()) > max_bytes and lines:
            lines.pop()
            text = "\n".join(lines)

        return text


def discover_taxonomy(documents_dir: Path) -> Taxonomy:
    """Walk ~/Documents one level deep, collecting folder names and sample files."""
    if not documents_dir.exists():
        log.warning("Documents directory not found: %s", documents_dir)
        return Taxonomy()

    folders: list[FolderInfo] = []

    for entry in sorted(documents_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue

        subfolders: list[str] = []
        sample_files: list[str] = []

        for child in sorted(entry.iterdir()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                subfolders.append(child.name)
            elif child.is_file():
                sample_files.append(child.name)

        # Trim samples
        sample_files = sample_files[:MAX_SAMPLES]

        folders.append(FolderInfo(
            name=entry.name,
            subfolders=subfolders,
            sample_files=sample_files,
        ))

    log.debug("Discovered taxonomy: %d top-level folders", len(folders))
    return _enrich_taxonomy(documents_dir, Taxonomy(folders=folders))


def _enrich_taxonomy(documents_dir: Path, taxonomy: Taxonomy) -> Taxonomy:
    """Collect sample files from each subfolder and store in _subfolder_samples."""
    for folder in taxonomy.folders:
        folder_path = documents_dir / folder.name
        for sub in folder.subfolders:
            sub_path = folder_path / sub
            samples: list[str] = []
            if sub_path.is_dir():
                for f in sorted(sub_path.iterdir()):
                    if f.is_file() and not f.name.startswith("."):
                        samples.append(f.name)
                        if len(samples) >= 3:
                            break
            key = f"{folder.name}/{sub}"
            taxonomy._subfolder_samples[key] = samples

    return taxonomy
