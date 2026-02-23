"""LLM prompt templates for file classification."""

from __future__ import annotations

CLASSIFICATION_PROMPT = """\
You are a file organizer assistant. Classify each file as either:
- "move": belongs in the user's Documents folder. Specify the exact destination folder.
- "delete": transient file (installer, temp download, duplicate, cache).

The user's Documents folder structure:
{taxonomy}

For each file, also provide a confidence score from 0.0 to 1.0.
- Use high confidence (0.8-1.0) when the file clearly belongs somewhere.
- Use medium confidence (0.5-0.7) when you're somewhat sure.
- Use low confidence (0.0-0.4) when you're guessing.

Files to classify:
{file_list}

Respond ONLY with a JSON object containing a "files" array:
{{"files": [
  {{
    "file": "<filename>",
    "action": "move" or "delete",
    "destination": "<folder/subfolder path from Documents>" (only for move, omit for delete),
    "reason": "<brief explanation>",
    "confidence": <0.0 to 1.0>
  }}
]}}
"""


def build_classification_prompt(
    taxonomy_text: str,
    file_descriptions: list[str],
) -> str:
    """Build the full classification prompt with taxonomy and file list."""
    file_list = "\n".join(f"- {desc}" for desc in file_descriptions)
    return CLASSIFICATION_PROMPT.format(
        taxonomy=taxonomy_text,
        file_list=file_list,
    )
