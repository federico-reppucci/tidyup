"""Client for Apple Foundation Models via afm-cli subprocess."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger("tidydownloads")

# Regex to strip markdown code fences: ```json ... ``` or ``` ... ```
_CODE_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```",
    re.DOTALL,
)


class AppleFMError(Exception):
    pass


class AppleFMClient:
    """Calls Apple's on-device Foundation Model via afm-cli."""

    def generate(
        self,
        prompt: str,
        timeout: int = 120,
        on_token: Callable[[int], None] | None = None,
    ) -> dict[str, Any]:
        """Send a prompt to afm-cli and return parsed JSON response.

        The on_token callback is not used (afm-cli doesn't stream tokens),
        but accepted for interface compatibility with OllamaClient.
        """
        # Write prompt to a temp file (afm-cli reads from --file)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False,
        ) as f:
            f.write(prompt)
            prompt_path = Path(f.name)

        try:
            result = subprocess.run(
                [
                    "afm-cli",
                    "--system-prompt", "Respond ONLY with valid JSON. No markdown, no explanation.",
                    "--file", str(prompt_path),
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            raise AppleFMError(
                "afm-cli not found. Install with: brew install afm-cli"
            )
        except subprocess.TimeoutExpired:
            raise AppleFMError(
                f"Apple FM request timed out ({timeout}s)"
            )
        finally:
            prompt_path.unlink(missing_ok=True)

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise AppleFMError(f"afm-cli failed (exit {result.returncode}): {stderr}")

        stdout = result.stdout.strip()
        if not stdout:
            raise AppleFMError("afm-cli returned empty response")

        # Strip markdown code fences if present
        text = _strip_code_fences(stdout)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            log.debug("Raw afm-cli output: %s", stdout[:500])
            raise AppleFMError(f"Invalid JSON from Apple FM: {e}")

        # Normalize: if the model returns a bare list, wrap it in {"files": [...]}
        if isinstance(parsed, list):
            return {"files": parsed}
        return parsed

    def is_available(self) -> bool:
        """Check if afm-cli is installed (does NOT do a test generation — too slow on cold start)."""
        try:
            result = subprocess.run(
                ["afm-cli", "--help"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences wrapping JSON output."""
    match = _CODE_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text
