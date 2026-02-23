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


@dataclass
class Taxonomy:
    folders: list[FolderInfo] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        """Format taxonomy as text for the LLM prompt."""
        lines: list[str] = []
        for folder in self.folders:
            lines.append(f"{folder.name}/")
            for sub in folder.subfolders:
                samples = _get_samples_for(folder, sub)
                if samples:
                    example = ", ".join(samples)
                    lines.append(f"  ├── {sub}/ (e.g., {example})")
                else:
                    lines.append(f"  ├── {sub}/")
            if folder.sample_files:
                example = ", ".join(folder.sample_files[:3])
                lines.append(f"  (root files: {example})")
        return "\n".join(lines)


def _get_samples_for(folder: FolderInfo, subfolder_name: str) -> list[str]:
    """Get sample files list — stored as subfolder_name:samples in the full data."""
    # Samples are collected per-subfolder during discovery
    return []  # Filled during discovery via the enriched version


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
    """Add sample files from subfolders to the prompt text generation."""
    # Override to_prompt_text with enriched version that includes subfolder samples
    enriched_lines: list[str] = []

    for folder in taxonomy.folders:
        enriched_lines.append(f"{folder.name}/")
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
            if samples:
                example = ", ".join(samples)
                enriched_lines.append(f"  ├── {sub}/ (e.g., {example})")
            else:
                enriched_lines.append(f"  ├── {sub}/")

        if folder.sample_files:
            example = ", ".join(folder.sample_files[:3])
            enriched_lines.append(f"  (root files: {example})")

    # Store the enriched text
    taxonomy._enriched_text = "\n".join(enriched_lines)
    # Monkey-patch to_prompt_text to use enriched version
    original_to_prompt = taxonomy.to_prompt_text
    taxonomy.to_prompt_text = lambda: taxonomy._enriched_text  # type: ignore[assignment]
    return taxonomy
