"""LLM prompt templates for file classification."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tidydownloads.taxonomy import Taxonomy

CLASSIFICATION_PROMPT = """\
You are a file organizer. Classify each file into one of the folders below, or mark it for deletion.

FOLDERS:
{taxonomy}

RULES:
- "move": file belongs in a folder above. Set destination to the EXACT path.
- "delete": installer, temp file, incomplete download, cache, or binary.
- Pick the folder whose name best matches the file's content or topic.
- confidence: 0.7-1.0 = clearly matches, 0.5-0.6 = likely, 0.3-0.4 = guess.
- When unsure, pick the most likely folder at 0.5 confidence.

EXAMPLE:
Input: report.pdf (application/pdf, 2 MB)
Output: {{"file": "report.pdf", "action": "move",
"destination": "{example_dest}", "reason": "report", "confidence": 0.7}}
Input: setup.dmg (application/x-apple-diskimage, 85 MB)
Output: {{"file": "setup.dmg", "action": "delete",
"destination": "", "reason": "installer", "confidence": 0.95}}

FILES TO CLASSIFY:
{file_list}

Respond ONLY with valid JSON (no text before or after):
{{"files": [{{"file": "<name>", "action": "move"|"delete",
"destination": "<exact path>", "reason": "<why>",
"confidence": <0.0-1.0>}}]}}
"""


def build_classification_prompt(
    taxonomy_text: str,
    file_descriptions: list[str],
    taxonomy: Taxonomy | None = None,
) -> str:
    """Build the full classification prompt with taxonomy and file list."""
    # Pick a middle-of-the-list folder for the example to avoid biasing first/last
    example_dest = "Work"
    if taxonomy and taxonomy.folders:
        mid = len(taxonomy.folders) // 2
        example_dest = taxonomy.folders[mid].name

    file_list = "\n".join(f"- {desc}" for desc in file_descriptions)
    return CLASSIFICATION_PROMPT.format(
        taxonomy=taxonomy_text,
        file_list=file_list,
        example_dest=example_dest,
    )


# --- Stage 2: Subfolder refinement prompt (kept for backward compat) ---

SUBFOLDER_PROMPT = """\
These files belong in the "{folder}" folder. Pick the best subfolder for each file.

SUBFOLDERS:
{subfolders}

FILES:
{file_list}

Respond ONLY with JSON:
{{"files": [{{"file": "<name>", "subfolder": "<exact subfolder name>"}}]}}
"""


def build_subfolder_prompt(
    folder_name: str,
    subfolder_names: list[str],
    file_descriptions: list[str],
) -> str:
    """Build the subfolder refinement prompt for stage 2."""
    subfolders = "\n".join(f"- {s}" for s in subfolder_names)
    file_list = "\n".join(f"- {desc}" for desc in file_descriptions)
    return SUBFOLDER_PROMPT.format(
        folder=folder_name,
        subfolders=subfolders,
        file_list=file_list,
    )
