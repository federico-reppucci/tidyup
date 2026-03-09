"""LLM prompt template for file organization."""

from __future__ import annotations

ORGANIZE_PROMPT = """\
You are a file organizer. Given a list of files currently in a Downloads folder, \
propose a clean folder structure to organize them in-place.

RULES:
- IMPORTANT: You MUST include EVERY file listed above in your response. Do not skip any.
- Group files by topic, project, or type into 3-10 top-level folders.
- Junk files (installers, temp files, incomplete downloads, caches, duplicates) go to "Trash".
- Use "" (empty string) for files that should stay in the root of Downloads.
- Folder names should be short, descriptive, and use Title Case (e.g. "Work", "Finance/Tax").
- Nesting is allowed up to 2 levels (e.g. "Work/Reports").
- Each file's current path is shown — if it's already well-organized, keep the same folder.

FILES TO ORGANIZE:
{file_list}

Respond ONLY with valid JSON (no text before or after):
{{"files": [{{"file": "<current_relative_path>", "folder": "<destination_folder>", \
"reason": "<short_reason>"}}]}}
"""


RETRY_PROMPT = """\
You are a file organizer. Your previous response was missing some files. \
You MUST classify EVERY file below — do not skip any.

FILES TO CLASSIFY:
{file_list}

Respond ONLY with valid JSON (no text before or after):
{{"files": [{{"file": "<current_relative_path>", "folder": "<destination_folder>", \
"reason": "<short_reason>"}}]}}
"""


def build_organize_prompt(file_descriptions: list[str]) -> str:
    """Build the full organize prompt with file descriptions."""
    file_list = "\n".join(f"- {desc}" for desc in file_descriptions)
    return ORGANIZE_PROMPT.format(file_list=file_list)


def build_retry_prompt(file_descriptions: list[str]) -> str:
    """Build a retry prompt for files the LLM missed on the first pass."""
    file_list = "\n".join(f"- {desc}" for desc in file_descriptions)
    return RETRY_PROMPT.format(file_list=file_list)
