"""LLM prompt templates for file classification."""

from __future__ import annotations

import json

CLASSIFICATION_PROMPT = """\
You are a file organizer. Classify each file into one of the folders below, or mark it for deletion.

FOLDERS:
{taxonomy}

RULES:
- "move": file belongs in a folder above. Use the EXACT folder path shown (e.g. "04 Education/MBA").
- "delete": installer, temp file, incomplete download, or cache file.
- confidence: 0.8-1.0 = obvious match, 0.5-0.7 = likely, 0.0-0.4 = guessing.

EXAMPLES:
{examples}

FILES TO CLASSIFY:
{file_list}

Respond ONLY with JSON:
{{"files": [{{"file": "<name>", "action": "move"|"delete", "destination": "<folder path>", "reason": "<why>", "confidence": <0-1>}}]}}
"""

# Generic examples that work with any taxonomy — they demonstrate output
# format and reasoning, not specific folder names.
FEW_SHOT_EXAMPLES = [
    {
        "input": "quarterly-report-Q3.pdf (application/pdf, 2.1 MB)",
        "output": {
            "file": "quarterly-report-Q3.pdf",
            "action": "move",
            "destination": "Work",
            "reason": "Business quarterly report",
            "confidence": 0.8,
        },
    },
    {
        "input": "chrome-installer.dmg (application/x-apple-diskimage, 85 MB)",
        "output": {
            "file": "chrome-installer.dmg",
            "action": "delete",
            "destination": "",
            "reason": "macOS disk image installer",
            "confidence": 0.95,
        },
    },
    {
        "input": "ml-notes.ipynb (application/json, 340 KB) — content preview: import pandas as pd...",
        "output": {
            "file": "ml-notes.ipynb",
            "action": "move",
            "destination": "Education/Learning",
            "reason": "Machine learning study notebook",
            "confidence": 0.75,
        },
    },
]


def _format_examples() -> str:
    """Format few-shot examples for the prompt."""
    lines: list[str] = []
    for ex in FEW_SHOT_EXAMPLES:
        lines.append(f"Input: {ex['input']}")
        lines.append(f"Output: {json.dumps(ex['output'])}")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_classification_prompt(
    taxonomy_text: str,
    file_descriptions: list[str],
) -> str:
    """Build the full classification prompt with taxonomy and file list."""
    file_list = "\n".join(f"- {desc}" for desc in file_descriptions)
    return CLASSIFICATION_PROMPT.format(
        taxonomy=taxonomy_text,
        file_list=file_list,
        examples=_format_examples(),
    )


# --- Stage 2: Subfolder refinement prompt ---

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
