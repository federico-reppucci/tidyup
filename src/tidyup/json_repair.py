"""Best-effort repair of malformed JSON from LLM responses."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

__all__ = ["repair_json"]

log = logging.getLogger("tidyup")


def repair_json(text: str) -> Any:
    """Parse JSON text, attempting repairs if initial parsing fails.

    Tries json.loads() first (fast path). On failure, applies a sequence of
    repairs and retries after each:
      1. Extract the JSON substring (strip surrounding non-JSON text)
      2. Fix commas (trailing commas, missing commas between brackets)
      3. Close unclosed brackets

    Raises the original json.JSONDecodeError if all repairs fail.
    """
    original_err: json.JSONDecodeError | None = None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        original_err = e

    repairs = [_extract_json_substring, _fix_commas, _close_unclosed_brackets]
    current = text

    for repair_fn in repairs:
        current = repair_fn(current)
        try:
            result = json.loads(current)
            log.warning("JSON repaired by %s", repair_fn.__name__)
            return result
        except json.JSONDecodeError:
            continue

    raise original_err


def _extract_json_substring(text: str) -> str:
    """Find the first top-level JSON object or array via balanced bracket scanning."""
    start = -1
    open_char = ""
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            open_char = ch
            break

    if start == -1:
        return text

    close_char = "}" if open_char == "{" else "]"
    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            if in_string:
                escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]

    # No balanced close found — return from start to end (will be fixed by later repairs)
    return text[start:]


def _fix_commas(text: str) -> str:
    """Remove trailing commas and insert missing commas between adjacent brackets."""
    # Remove trailing commas before ] or }
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # Insert missing commas between }{ and ][
    text = re.sub(r"(\})\s*(\{)", r"\1,\2", text)
    text = re.sub(r"(\])\s*(\[)", r"\1,\2", text)
    return text


def _close_unclosed_brackets(text: str) -> str:
    """Append missing closing brackets/braces for truncated JSON."""
    openers: list[str] = []
    in_string = False
    escape = False

    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            if in_string:
                escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            openers.append("}")
        elif ch == "[":
            openers.append("]")
        elif ch in "}]" and openers and openers[-1] == ch:
            openers.pop()

    # Close in reverse order
    return text + "".join(reversed(openers))
